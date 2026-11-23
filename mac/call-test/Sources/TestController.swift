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

    let folder: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let url = base.appendingPathComponent("Treadwell Call Test", isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }()

    var anyRunning: Bool { runs.contains { $0.running } }
    var anyDone: Bool { runs.contains { $0.done } }

    init() {
        mic = AVCaptureDevice.authorizationStatus(for: .audio) == .authorized ? .ok : .notYet
        openLog()
        write("Mac: \(macModel()), \(ProcessInfo.processInfo.operatingSystemVersionString)")
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
        let them = folder.appendingPathComponent("test\(id)-them.m4a")
        let you = folder.appendingPathComponent("test\(id)-you.m4a")
        try? FileManager.default.removeItem(at: them)
        try? FileManager.default.removeItem(at: you)
        runs[i].error = nil
        do {
            try tap.start(writingTo: them)
            try micRecorder.start(writingTo: you)
        } catch {
            tap.stop(); micRecorder.stop()
            runs[i].error = "Couldn't start: \(error)"
            write("Test \(id): couldn't start: \(error)")
            return
        }
        runs[i].running = true
        runs[i].started = Date()
        runs[i].seconds = 0
        write("Test \(id) started. Speakers/headset: \(tap.outputName). Microphone: \(micRecorder.inputName)")
        lastProcesses = []
        logProcesses()
        meterTimer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { _ in
            Task { @MainActor in self.tick() }
        }
        watchTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { _ in
            Task { @MainActor in self.logProcesses() }
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
        let t = runs[i].them!, y = runs[i].you!
        write("Test \(id) stopped after \(runs[i].seconds) s. Other person: sound in \(t.withSound) of \(t.total) s. You: sound in \(y.withSound) of \(y.total) s.")
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
