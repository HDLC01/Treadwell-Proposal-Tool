// What the window does: the two Allow checks, the two test calls, and sending the results.
import AppKit
import AVFoundation
import Foundation

enum Check: Equatable { case notYet, checking, ok, problem(String) }

struct TestRun: Identifiable {
    let id: Int
    let title: String
    let hint: String
    var running = false
    var started: Date?
    var seconds = 0
    var them: (withSound: Int, total: Int)?
    var you: (withSound: Int, total: Int)?
    var error: String?
    var done: Bool { them != nil }
}

@MainActor
final class TestController: ObservableObject {
    @Published var mic: Check = .notYet
    @Published var callAudio: Check = .notYet
    @Published var runs = [
        TestRun(id: 1, title: "Test call 1: with AirPods", hint: "Put your AirPods in, then call a Treadwell colleague from this Mac."),
        TestRun(id: 2, title: "Test call 2: on the Mac's speakers", hint: "Take your AirPods out, then call the same colleague again."),
    ]
    @Published var themLevel: Float = -120
    @Published var youLevel: Float = -120
    @Published var sendNote = ""

    private let tap = SystemAudioTap()
    private let micRecorder = MicRecorder()
    private var meterTimer: Timer?
    private var watchTimer: Timer?
    private var lastProcesses: Set<AudioProcess> = []
    private var log: FileHandle?
    /// Each recorder restart during a call writes a new numbered part, so nothing recorded is lost.
    private var themPart = 1
    private var youPart = 1
    /// A restart that failed is tried again every second; only its first failure is logged.
    private var themDown = false
    private var youDown = false
    /// A recorder that keeps stopping gives up after this many parts; the log shows each restart.
    private let maxParts = 20

    let folder: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let url = base.appendingPathComponent("Treadwell Call Test", isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }()

    var anyRunning: Bool { runs.contains { $0.running } }
    var anyDone: Bool { runs.contains { $0.done } }

    /// The one window's controller, so quitting can finish a running test's files first.
    static weak var shared: TestController?

    init() {
        mic = AVCaptureDevice.authorizationStatus(for: .audio) == .authorized ? .ok : .notYet
        openLog()
        write("Mac: \(macModel()), \(ProcessInfo.processInfo.operatingSystemVersionString)")
        TestController.shared = self
    }

    /// Quitting or closing the window mid-call: stop like the Stop button, so the recordings are
    /// finished and playable instead of cut off.
    func stopBeforeQuit() {
        for run in runs where run.running {
            write("Test \(run.id): the app was closed during the call, stopping it first.")
            stop(run.id)
        }
        try? log?.synchronize()
    }

    // MARK: Allow

    func allowMicrophone() {
        mic = .checking
        AVCaptureDevice.requestAccess(for: .audio) { granted in
            Task { @MainActor in
                self.mic = granted ? .ok : .problem("The microphone is off for this app.")
                self.write("Microphone permission: \(granted ? "allowed" : "denied")")
            }
        }
    }

    /// Starts listening to the Mac's sound (which makes macOS ask the first time), plays a short
    /// sound, and checks the recorder heard it. If permission is off, the recorder hears silence.
    func allowCallAudio() {
        callAudio = .checking
        do {
            try tap.start(writingTo: nil)
        } catch {
            callAudio = .problem("Couldn't listen to the Mac's sound: \(error).")
            write("Call audio check: \(error)")
            return
        }
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 800_000_000)
            NSSound(named: "Glass")?.play()
            try? await Task.sleep(nanoseconds: 1_700_000_000)
            let heard = self.tap.meter.peak
            self.tap.stop()
            if heard > -70 {
                self.callAudio = .ok
                self.write("Call audio check: heard the test sound (\(Int(heard)) dB) on \(self.tap.outputName)")
            } else {
                self.callAudio = .problem("The app couldn't hear the Mac's sound. Turn it on in System Settings, then press Check again.")
                self.write("Call audio check: silence on \(self.tap.outputName) (permission off, or volume muted)")
            }
        }
    }

    func openSoundSettings() {
        let urls = ["x-apple.systempreferences:com.apple.preference.security?Privacy_AudioCapture",
                    "x-apple.systempreferences:com.apple.preference.security?Privacy"]
        for s in urls { if let u = URL(string: s), NSWorkspace.shared.open(u) { return } }
    }

    // MARK: Test calls

    func start(_ id: Int) {
        guard let i = runs.firstIndex(where: { $0.id == id }), !anyRunning else { return }
        // "Do it again" replaces every file from the earlier try, restart parts included.
        if let names = try? FileManager.default.contentsOfDirectory(atPath: folder.path) {
            for name in names where name.hasPrefix("test\(id)-") {
                try? FileManager.default.removeItem(at: folder.appendingPathComponent(name))
            }
        }
        themPart = 1; youPart = 1; themDown = false; youDown = false
        runs[i].error = nil
        do {
            try tap.start(writingTo: partFile(id, "them", 1))
            try micRecorder.start(writingTo: partFile(id, "you", 1))
        } catch {
            tap.stop(); micRecorder.stop()
            runs[i].error = "Couldn't start: \(error)"
            write("Test \(id): couldn't start: \(error)")
            return
        }
        runs[i].running = true
        runs[i].started = Date()
        runs[i].seconds = 0
        write("Test \(id) started. Speakers/headset: \(tap.outputName). Microphone: \(micRecorder.inputName) (\(micRecorder.channels) channel(s))")
        write("Test \(id): \(tap.setupNote)")
        lastProcesses = []
        logProcesses()
        meterTimer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { _ in
            Task { @MainActor in self.tick() }
        }
        watchTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { _ in
            Task { @MainActor in
                self.logProcesses()
                self.keepRecordersGoing()
            }
        }
    }

    private func partFile(_ id: Int, _ who: String, _ part: Int) -> URL {
        folder.appendingPathComponent(part == 1 ? "test\(id)-\(who).m4a" : "test\(id)-\(who)-part\(part).m4a")
    }

    /// Restarts a recorder that stopped mid-call, into the next numbered part, and logs why.
    private func keepRecordersGoing() {
        guard let id = runs.first(where: { $0.running })?.id else { return }

        if let e = tap.writeErrors.takeNew() {
            write("Test \(id): saving the other person's part \(themPart) failed: \(e). The meter still counts, but that file may be empty.")
        }
        if let e = micRecorder.writeErrors.takeNew() {
            write("Test \(id): saving your part \(youPart) failed: \(e). The meter still counts, but that file may be empty.")
        }

        let themWhy = themDown ? "the last restart failed" : tap.problem()
        if let why = themWhy, themPart < maxParts {
            tap.stop()
            if !themDown { themPart += 1 }
            do {
                try tap.start(writingTo: partFile(id, "them", themPart), resetMeter: false)
                themDown = false
                write("Test \(id): other person's recorder restarted as part \(themPart) because \(why). Now on \(tap.outputName); \(tap.setupNote).")
            } catch {
                if !themDown { write("Test \(id): other person's recorder couldn't restart after \(why): \(error). Trying every second.") }
                themDown = true
            }
        }

        let youWhy = youDown ? "the last restart failed" : micRecorder.problem()
        if let why = youWhy, youPart < maxParts {
            micRecorder.stop()
            if !youDown { youPart += 1 }
            do {
                try micRecorder.start(writingTo: partFile(id, "you", youPart), resetMeter: false)
                youDown = false
                write("Test \(id): your recorder restarted as part \(youPart) because \(why). Now on \(micRecorder.inputName) (\(micRecorder.channels) channel(s)).")
            } catch {
                if !youDown { write("Test \(id): your recorder couldn't restart after \(why): \(error). Trying every second.") }
                youDown = true
            }
        }
    }

    func stop(_ id: Int) {
        guard let i = runs.firstIndex(where: { $0.id == id }), runs[i].running else { return }
        meterTimer?.invalidate(); watchTimer?.invalidate()
        tap.stop(); micRecorder.stop()
        runs[i].running = false
        runs[i].them = tap.meter.summary
        runs[i].you = micRecorder.meter.summary
        themLevel = -120; youLevel = -120
        if let e = tap.writeErrors.takeNew() { write("Test \(id): saving the other person's part \(themPart) failed: \(e).") }
        if let e = micRecorder.writeErrors.takeNew() { write("Test \(id): saving your part \(youPart) failed: \(e).") }
        let t = runs[i].them!, y = runs[i].you!
        write("Test \(id) stopped after \(runs[i].seconds) s. Other person: sound in \(t.withSound) of \(t.total) s, \(themPart) part(s). You: sound in \(y.withSound) of \(y.total) s, \(youPart) part(s).")
    }

    private func tick() {
        themLevel = tap.meter.level
        youLevel = micRecorder.meter.level
        if let i = runs.firstIndex(where: { $0.running }), let s = runs[i].started {
            runs[i].seconds = Int(Date().timeIntervalSince(s))
        }
    }

    private func logProcesses() {
        let now = Set(audioProcesses())
        for p in now.subtracting(lastProcesses) { write("  sound on:  \(p.line)") }
        for p in lastProcesses.subtracting(now) { write("  sound off: \(p.line)") }
        lastProcesses = now
    }

    // MARK: Results

    func sendResults() {
        write("Results sent from the app.")
        try? log?.synchronize()
        let zip = FileManager.default.temporaryDirectory.appendingPathComponent("Treadwell-Call-Test-Results.zip")
        try? FileManager.default.removeItem(at: zip)
        let ditto = Process()
        ditto.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
        ditto.arguments = ["-c", "-k", "--keepParent", folder.path, zip.path]
        do { try ditto.run(); ditto.waitUntilExit() } catch {
            sendNote = "Couldn't pack the results: \(error)"
            return
        }
        if let mail = NSSharingService(named: .composeEmail) {
            mail.subject = "Treadwell call test results"
            if mail.canPerform(withItems: [zip]) {
                mail.perform(withItems: [zip])
                sendNote = "Mail is open with the results attached. Send it to Hanz."
                return
            }
        }
        NSWorkspace.shared.activateFileViewerSelecting([zip])
        sendNote = "Mail isn't set up, so the results file is shown in Finder. Email it to Hanz."
    }

    func showFolder() { NSWorkspace.shared.activateFileViewerSelecting([folder]) }

    // MARK: Log

    private func openLog() {
        let url = folder.appendingPathComponent("log.txt")
        if !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(atPath: url.path, contents: nil)
        }
        log = try? FileHandle(forWritingTo: url)
        _ = try? log?.seekToEnd()
    }

    func write(_ line: String) {
        let stamp = ISO8601DateFormatter().string(from: Date())
        if let data = "\(stamp) \(line)\n".data(using: .utf8) { try? log?.write(contentsOf: data) }
    }

    private func macModel() -> String {
        var size = 0
        sysctlbyname("hw.model", nil, &size, nil, 0)
        guard size > 0 else { return "unknown" }
        var buffer = [CChar](repeating: 0, count: size)
        sysctlbyname("hw.model", &buffer, &size, nil, 0)
        return String(cString: buffer)
    }
}
