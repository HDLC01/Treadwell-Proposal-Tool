// The two recorders and the process watcher for the call test.
//
// SystemAudioTap: a Core Audio process tap over everything the Mac plays (macOS 14.2+). During a
//   call relayed from RJ's iPhone, the other person's voice is played by a system process, so a
//   global tap should hear it. Whether it does is exactly what this test finds out.
// MicRecorder: RJ's own microphone through AVAudioEngine.
// audioProcesses(): which programs are playing or recording sound right now, so the log names the
//   process that carries call audio on RJ's macOS version.
import AVFoundation
import AudioToolbox
import CoreAudio
import Foundation

struct AudioError: Error, CustomStringConvertible {
    let step: String
    let status: OSStatus
    var description: String { "\(step) failed (\(status))" }
}

/// Live level plus a per-second count of how many seconds had sound in them.
final class LevelMeter {
    private let lock = NSLock()
    private var current: Float = -120
    private var loudest: Float = -120
    private var frames: Double = 0
    private var sumSquares: Double = 0
    private var secondsTotal = 0
    private var secondsWithSound = 0
    private var lastFed = Date()
    /// Quieter than this for a whole second counts as silence.
    static let soundFloorDB: Float = -50

    func reset() {
        lock.lock(); defer { lock.unlock() }
        current = -120; loudest = -120; frames = 0; sumSquares = 0; secondsTotal = 0; secondsWithSound = 0
        lastFed = Date()
    }

    /// After a restart: keep the counts, but don't call the recorder stalled before its first sound data.
    func markAlive() {
        lock.lock(); defer { lock.unlock() }
        lastFed = Date()
    }

    /// Seconds since the recorder last handed over sound data. Both recorders get data many times a
    /// second even when nobody talks, so a gap of seconds means the recorder has stopped.
    var secondsSinceFeed: TimeInterval {
        lock.lock(); defer { lock.unlock() }
        return Date().timeIntervalSince(lastFed)
    }

    func feed(_ buffer: AVAudioPCMBuffer) {
        guard let channels = buffer.floatChannelData else { return }
        let n = Int(buffer.frameLength)
        let chans = Int(buffer.format.channelCount)
        let stride = buffer.format.isInterleaved ? chans : 1
        let lanes = buffer.format.isInterleaved ? 1 : chans
        guard n > 0, lanes > 0 else { return }
        var sum: Double = 0
        var count = 0
        for c in 0..<lanes {
            let p = channels[c]
            for i in 0..<(n * stride) {
                let v = Double(p[i])
                sum += v * v
            }
            count += n * stride
        }
        let rms = count > 0 ? sqrt(sum / Double(count)) : 0
        let db = rms > 0 ? Float(20 * log10(rms)) : -120
        let rate = buffer.format.sampleRate
        lock.lock()
        lastFed = Date()
        current = db
        loudest = max(loudest, db)
        sumSquares += sum
        frames += Double(n)
        if rate > 0 && frames >= rate {
            let secRMS = sqrt(sumSquares / max(1, frames * Double(chans)))
            let secDB = secRMS > 0 ? Float(20 * log10(secRMS)) : -120
            secondsTotal += 1
            if secDB > LevelMeter.soundFloorDB { secondsWithSound += 1 }
            frames = 0; sumSquares = 0
        }
        lock.unlock()
    }

    var level: Float { lock.lock(); defer { lock.unlock() }; return current }
    var peak: Float { lock.lock(); defer { lock.unlock() }; return loudest }
    var summary: (withSound: Int, total: Int) {
        lock.lock(); defer { lock.unlock() }
        return (secondsWithSound, secondsTotal)
    }
}

private func aacSettings(_ fmt: AVAudioFormat) -> [String: Any] {
    [AVFormatIDKey: kAudioFormatMPEG4AAC,
     AVSampleRateKey: fmt.sampleRate,
     AVNumberOfChannelsKey: min(fmt.channelCount, 2),
     AVEncoderBitRateKey: 96_000]
}

private func address(_ selector: AudioObjectPropertySelector) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: selector, mScope: kAudioObjectPropertyScopeGlobal,
                               mElement: kAudioObjectPropertyElementMain)
}

private func stringProperty(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String? {
    var addr = address(selector)
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    var value: Unmanaged<CFString>?
    let status = withUnsafeMutablePointer(to: &value) {
        AudioObjectGetPropertyData(object, &addr, 0, nil, &size, $0)
    }
    guard status == noErr, let v = value else { return nil }
    return v.takeRetainedValue() as String
}

private func uint32Property(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector) -> UInt32? {
    var addr = address(selector)
    var size = UInt32(MemoryLayout<UInt32>.size)
    var value: UInt32 = 0
    guard AudioObjectGetPropertyData(object, &addr, 0, nil, &size, &value) == noErr else { return nil }
    return value
}

/// The device the Mac plays (or records) through right now. Output uses the main output setting,
/// which is where call audio goes, not the separate one for alert sounds.
private func defaultDevice(input: Bool) throws -> AudioObjectID {
    var addr = address(input ? kAudioHardwarePropertyDefaultInputDevice : kAudioHardwarePropertyDefaultOutputDevice)
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    var device = AudioObjectID(kAudioObjectUnknown)
    let status = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &device)
    guard status == noErr, device != kAudioObjectUnknown else {
        throw AudioError(step: input ? "find the microphone" : "find the Mac's speakers", status: status)
    }
    return device
}

private func nominalRate(_ device: AudioObjectID) -> Float64? {
    var addr = address(kAudioDevicePropertyNominalSampleRate)
    var size = UInt32(MemoryLayout<Float64>.size)
    var value: Float64 = 0
    guard AudioObjectGetPropertyData(device, &addr, 0, nil, &size, &value) == noErr else { return nil }
    return value
}

private func deviceName(_ device: AudioObjectID) -> String {
    stringProperty(device, kAudioObjectPropertyName) ?? "unknown"
}

/// How long a recorder may go without sound data before it counts as stopped.
private let stalledAfter: TimeInterval = 2

final class SystemAudioTap {
    let meter = LevelMeter()
    private var tapID = AudioObjectID(kAudioObjectUnknown)
    private var aggregateID = AudioObjectID(kAudioObjectUnknown)
    private var procID: AudioDeviceIOProcID?
    private var format: AVAudioFormat?
    private var file: AVAudioFile?
    private let queue = DispatchQueue(label: "treadwell.calltest.tap", qos: .userInitiated)
    private(set) var outputName = ""
    private var outputID = AudioObjectID(kAudioObjectUnknown)
    private var outputRate: Float64 = 0

    var isRunning: Bool { aggregateID != kAudioObjectUnknown }

    /// `resetMeter: false` is a restart in the middle of a test call: the seconds counts carry on.
    func start(writingTo url: URL?, resetMeter: Bool = true) throws {
        if resetMeter { meter.reset() } else { meter.markAlive() }
        let description = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
        description.uuid = UUID()
        description.name = "Treadwell call test"
        description.isPrivate = true
        description.muteBehavior = .unmuted

        var status = AudioHardwareCreateProcessTap(description, &tapID)
        guard status == noErr else { throw AudioError(step: "start listening to the Mac's sound", status: status) }

        var asbd = AudioStreamBasicDescription()
        var addr = address(kAudioTapPropertyFormat)
        var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        status = AudioObjectGetPropertyData(tapID, &addr, 0, nil, &size, &asbd)
        guard status == noErr, let fmt = AVAudioFormat(streamDescription: &asbd) else {
            stop(); throw AudioError(step: "read the sound format", status: status)
        }
        format = fmt

        let output: AudioObjectID
        do { output = try defaultDevice(input: false) } catch { stop(); throw error }
        outputID = output
        outputRate = nominalRate(output) ?? 0
        outputName = deviceName(output)
        guard let outputUID = stringProperty(output, kAudioDevicePropertyDeviceUID) else {
            stop(); throw AudioError(step: "read the speakers' id", status: -1)
        }
        let aggregate: [String: Any] = [
            kAudioAggregateDeviceNameKey: "Treadwell call test",
            kAudioAggregateDeviceUIDKey: UUID().uuidString,
            kAudioAggregateDeviceMainSubDeviceKey: outputUID,
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceIsStackedKey: false,
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceSubDeviceListKey: [[kAudioSubDeviceUIDKey: outputUID]],
            kAudioAggregateDeviceTapListKey: [[kAudioSubTapDriftCompensationKey: true,
                                               kAudioSubTapUIDKey: description.uuid.uuidString]],
        ]
        status = AudioHardwareCreateAggregateDevice(aggregate as CFDictionary, &aggregateID)
        guard status == noErr else { stop(); throw AudioError(step: "set up the recording device", status: status) }

        if let url {
            do {
                file = try AVAudioFile(forWriting: url, settings: aacSettings(fmt),
                                       commonFormat: fmt.commonFormat, interleaved: fmt.isInterleaved)
            } catch { stop(); throw error }
        }
        status = AudioDeviceCreateIOProcIDWithBlock(&procID, aggregateID, queue) { [weak self] _, input, _, _, _ in
            guard let self, let fmt = self.format,
                  let buffer = AVAudioPCMBuffer(pcmFormat: fmt, bufferListNoCopy: input, deallocator: nil)
            else { return }
            self.meter.feed(buffer)
            try? self.file?.write(from: buffer)
        }
        guard status == noErr else { stop(); throw AudioError(step: "attach the recorder", status: status) }
        status = AudioDeviceStart(aggregateID, procID)
        guard status == noErr else { stop(); throw AudioError(step: "start recording the Mac's sound", status: status) }
    }

    func stop() {
        if aggregateID != kAudioObjectUnknown {
            if let procID {
                AudioDeviceStop(aggregateID, procID)
                AudioDeviceDestroyIOProcID(aggregateID, procID)
            }
            AudioHardwareDestroyAggregateDevice(aggregateID)
        }
        if tapID != kAudioObjectUnknown { AudioHardwareDestroyProcessTap(tapID) }
        queue.sync { file = nil }
        procID = nil
        aggregateID = AudioObjectID(kAudioObjectUnknown)
        tapID = AudioObjectID(kAudioObjectUnknown)
    }

    /// Why this recorder needs a restart, or nil when it's fine. A call switches AirPods into call
    /// mode (a new sample rate) or moves the sound to another device; either can stop the recording
    /// device this recorder built at Start.
    func problem() -> String? {
        guard isRunning else { return nil }
        if let now = try? defaultDevice(input: false), now != outputID {
            return "the sound moved from \(outputName) to \(deviceName(now))"
        }
        if outputRate > 0, let rate = nominalRate(outputID), rate != outputRate {
            return "\(outputName) changed from \(Int(outputRate)) Hz to \(Int(rate)) Hz"
        }
        let gap = meter.secondsSinceFeed
        if gap > stalledAfter { return "no sound data for \(Int(gap)) s" }
        return nil
    }
}

final class MicRecorder {
    let meter = LevelMeter()
    private var engine = AVAudioEngine()
    private let fileLock = NSLock()
    private var file: AVAudioFile?
    private var inputID = AudioObjectID(kAudioObjectUnknown)
    private(set) var inputName = ""
    private(set) var channels = 0
    private(set) var isRunning = false

    /// `resetMeter: false` is a restart in the middle of a test call: the seconds counts carry on.
    func start(writingTo url: URL?, resetMeter: Bool = true) throws {
        if resetMeter { meter.reset() } else { meter.markAlive() }
        engine = AVAudioEngine()
        let input = engine.inputNode
        let fmt = input.outputFormat(forBus: 0)
        guard fmt.sampleRate > 0 else { throw AudioError(step: "find a microphone", status: -1) }
        inputID = (try? defaultDevice(input: true)) ?? AudioObjectID(kAudioObjectUnknown)
        inputName = inputID != kAudioObjectUnknown ? deviceName(inputID)
            : (AVCaptureDevice.default(for: .audio)?.localizedName ?? "unknown")
        channels = Int(fmt.channelCount)
        var newFile: AVAudioFile?
        if let url {
            newFile = try AVAudioFile(forWriting: url, settings: aacSettings(fmt),
                                      commonFormat: fmt.commonFormat, interleaved: fmt.isInterleaved)
        }
        fileLock.lock(); file = newFile; fileLock.unlock()
        input.installTap(onBus: 0, bufferSize: 4096, format: fmt) { [weak self] buffer, _ in
            guard let self else { return }
            self.meter.feed(buffer)
            self.fileLock.lock()
            try? self.file?.write(from: buffer)
            self.fileLock.unlock()
        }
        engine.prepare()
        do { try engine.start() } catch { stop(); throw error }
        isRunning = true
    }

    func stop() {
        isRunning = false
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        fileLock.lock(); file = nil; fileLock.unlock()
    }

    /// Why this recorder needs a restart, or nil when it's fine. The recorder stops by itself when
    /// the Mac's audio setup changes, for example when AirPods switch into call mode.
    func problem() -> String? {
        guard isRunning else { return nil }
        if !engine.isRunning { return "the microphone recorder stopped (the audio setup changed)" }
        if let now = try? defaultDevice(input: true), inputID != kAudioObjectUnknown, now != inputID {
            return "the microphone moved from \(inputName) to \(deviceName(now))"
        }
        let gap = meter.secondsSinceFeed
        if gap > stalledAfter { return "no sound data for \(Int(gap)) s" }
        return nil
    }
}

struct AudioProcess: Hashable {
    let pid: Int32
    let name: String
    let playing: Bool
    let recording: Bool
    var line: String {
        "\(name) (pid \(pid))\(playing ? " playing" : "")\(recording ? " recording" : "")"
    }
}

/// Every program that is playing or recording sound right now (macOS 14.2+).
func audioProcesses() -> [AudioProcess] {
    let system = AudioObjectID(kAudioObjectSystemObject)
    var addr = address(kAudioHardwarePropertyProcessObjectList)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(system, &addr, 0, nil, &size) == noErr, size > 0 else { return [] }
    var ids = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    guard AudioObjectGetPropertyData(system, &addr, 0, nil, &size, &ids) == noErr else { return [] }
    var out: [AudioProcess] = []
    for id in ids {
        let playing = (uint32Property(id, kAudioProcessPropertyIsRunningOutput) ?? 0) != 0
        let recording = (uint32Property(id, kAudioProcessPropertyIsRunningInput) ?? 0) != 0
        guard playing || recording else { continue }
        let pid = Int32(bitPattern: uint32Property(id, kAudioProcessPropertyPID) ?? 0)
        var name = stringProperty(id, kAudioProcessPropertyBundleID) ?? ""
        if name.isEmpty { name = processPath(pid) }
        out.append(AudioProcess(pid: pid, name: name, playing: playing, recording: recording))
    }
    return out.sorted { $0.name < $1.name }
}

private func processPath(_ pid: Int32) -> String {
    var buffer = [CChar](repeating: 0, count: 4096)
    let n = proc_pidpath(pid, &buffer, UInt32(buffer.count))
    return n > 0 ? String(cString: buffer) : "unknown"
}
