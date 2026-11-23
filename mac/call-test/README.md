# Treadwell Call Test

A one-window Mac app that checks one thing before we build automatic call recording: can an app on
RJ's Mac hear **both** people on a call he places from his Mac on his Verizon number? Apple doesn't
document it, so we test it.

It records two short files per test call, the other person (everything the Mac plays) and RJ (his
microphone), and a log naming every program that played or recorded sound during the call. Nothing
leaves the Mac until RJ presses **Send results**.

## For RJ (about 15 minutes)

**Before you start:**

- Apple menu → **About This Mac**. It should say **Apple M1** or newer and **macOS 26** or newer.
  If not, stop and tell Hanz.
- Your Mac must be able to call from your Verizon number. On your iPhone: **Settings → Apps →
  Phone → Calls on Other Devices**, switch it on and switch your Mac on. On the Mac: open
  **FaceTime → Settings** and tick **Calls from iPhone**. Keep the iPhone nearby, on the same
  Wi-Fi.
- Check it once: call your own voicemail or a colleague from the Mac's FaceTime app. If the Mac
  can't place the call, stop and tell Hanz.

1. **Open the file Hanz sent** (`Treadwell-Call-Test.zip`). Drag **Treadwell Call Test** into
   **Applications**.
2. **Open it.** The first time, the Mac says it can't check the app. Click **Done**, then open
   **System Settings → Privacy & Security**, scroll down and click **Open Anyway**. You only do this
   once.
3. **Step 1, Allow:** click **Allow** next to *Microphone* and say yes. Then click **Allow** next to
   *The Mac's sound*. You'll hear a short chime. If the Mac asks to record its sound, say yes. If it
   shows a warning, click **Open System Settings**, switch **Treadwell Call Test** on, and click
   **Check again**.
4. **Step 2, test call 1:** put your AirPods in, press **Start**, then call a Treadwell colleague
   from the Mac (not a customer). Talk for about 3 minutes, hang up, press **Stop**.
5. **Test call 2:** take the AirPods out, press **Start**, call the same colleague again on the
   Mac's speakers. 3 minutes, hang up, **Stop**.
6. **Step 3:** press **Send results**. Mail opens with the results attached. Send it to Hanz. If
   you don't use the Mail app, a Finder window opens on the results file instead
   (`Treadwell-Call-Test-Results.zip`, about 10 MB). Attach it to an email to Hanz.

Both green bars should move during a call: *Other person* when your colleague talks, *You* when you
talk.

## For us

- Build: pushed to the `test-kit/call-recorder` branch, `.github/workflows/call-test-mac.yml` builds
  it on a GitHub Mac (`build.sh`, plain `swiftc`, no Xcode project) and uploads the zip as the run's
  artifact. Ad-hoc signed: no Apple Developer account, hence the one-time Open Anyway.
- Needs macOS 14.4+ (Core Audio process taps and the audio process list). The plan targets macOS 26.
- Results folder: `~/Library/Application Support/Treadwell Call Test/` with `test1-them.m4a`,
  `test1-you.m4a`, `test2-*`, and `log.txt`.
- A recorder that stops mid-call is restarted within about a second into a numbered part
  (`test1-them-part2.m4a`, …), and the log says why: the sound moved to another device, the device
  changed sample rate (AirPods entering call mode), or no sound data for over 2 s. The seconds
  counts run across all parts. More than one part means the background recorder must handle that
  same switch.
- **Pass:** each test's *Other person* track has speech for most of the call (the log line "sound in
  N of M s"), and the log names the process playing call audio. That process is what the background
  recorder will watch for.
- The other person is captured from everything the Mac plays, so notification sounds during the call
  land in that track too. That's fine for the test.
