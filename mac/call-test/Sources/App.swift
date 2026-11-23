// Treadwell Call Test: one window, three steps. See ../README.md.
import AppKit
import SwiftUI

@main
struct CallTestApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var controller = TestController()

    var body: some Scene {
        WindowGroup("Treadwell Call Test") {
            ContentView(controller: controller)
                .frame(minWidth: 520, minHeight: 640)
        }
        .windowResizability(.contentSize)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        MainActor.assumeIsolated { TestController.shared?.stopBeforeQuit() }
        return .terminateNow
    }
}

struct ContentView: View {
    @ObservedObject var controller: TestController

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Treadwell Call Test").font(.title.bold())
                Text("Three steps, about 15 minutes. Call a Treadwell colleague, never a customer.")
                    .foregroundStyle(.secondary)

                section("1. Allow") {
                    checkRow("Microphone", controller.mic, button: "Allow") { controller.allowMicrophone() }
                    checkRow("The Mac's sound (the other person's voice)", controller.callAudio,
                             button: controller.callAudio == .notYet ? "Allow" : "Check again") {
                        controller.allowCallAudio()
                    }
                    if case .problem = controller.callAudio {
                        Button("Open System Settings") { controller.openSoundSettings() }
                    }
                }

                section("2. Two short test calls") {
                    ForEach(controller.runs) { run in runView(run) }
                    if controller.anyRunning {
                        meter("Other person", controller.themLevel)
                        meter("You", controller.youLevel)
                    }
                }

                section("3. Send the results") {
                    Button("Send results") { controller.sendResults() }
                        .disabled(!controller.anyDone || controller.anyRunning)
                    if !controller.sendNote.isEmpty { Text(controller.sendNote).font(.callout) }
                    Button("Show the results folder") { controller.showFolder() }.buttonStyle(.link)
                }
            }
            .padding(24)
        }
    }

    private func section<C: View>(_ title: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(.headline)
            content()
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.secondary.opacity(0.08)))
    }

    private func checkRow(_ label: String, _ state: Check, button: String, action: @escaping () -> Void) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(symbol(state)).frame(width: 20)
                Text(label)
                Spacer()
                if state != .ok && state != .checking { Button(button, action: action) }
                if state == .checking { ProgressView().controlSize(.small) }
            }
            if case let .problem(msg) = state {
                Text(msg).font(.callout).foregroundStyle(.red)
            }
        }
    }

    private func symbol(_ state: Check) -> String {
        switch state {
        case .ok: return "✅"
        case .problem: return "⚠️"
        case .checking: return "…"
        case .notYet: return "○"
        }
    }

    private func runView(_ run: TestRun) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(run.title).bold()
                Spacer()
                if run.running {
                    Text(timeText(run.seconds)).monospacedDigit()
                    Button("Stop") { controller.stop(run.id) }.keyboardShortcut(.defaultAction)
                } else {
                    Button(run.done ? "Do it again" : "Start") { controller.start(run.id) }
                        .disabled(controller.anyRunning || controller.mic != .ok || controller.callAudio != .ok)
                }
            }
            if !run.running && !run.done {
                Text(run.hint + " Talk for about 3 minutes, hang up, then press Stop.").font(.callout).foregroundStyle(.secondary)
            }
            if let t = run.them, let y = run.you {
                Text("Other person: sound in \(t.withSound) of \(t.total) seconds. You: sound in \(y.withSound) of \(y.total) seconds.")
                    .font(.callout)
            }
            if let e = run.error { Text(e).font(.callout).foregroundStyle(.red) }
        }
        .padding(.vertical, 4)
    }

    private func meter(_ label: String, _ db: Float) -> some View {
        let fraction = max(0, min(1, (Double(db) + 60) / 60))
        return HStack {
            Text(label).frame(width: 110, alignment: .leading)
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 3).fill(Color.secondary.opacity(0.2))
                    RoundedRectangle(cornerRadius: 3).fill(Color.green).frame(width: geo.size.width * fraction)
                }
            }
            .frame(height: 10)
        }
    }

    private func timeText(_ s: Int) -> String { String(format: "%d:%02d", s / 60, s % 60) }
}
