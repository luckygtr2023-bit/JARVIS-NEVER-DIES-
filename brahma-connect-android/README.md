# J.A.R.V.I.S. Android Companion

Android companion for the J.A.R.V.I.S. desktop system
("Just A Rather Very Intelligent System", owner Lucky - Made by Lucky).

What this project is:
- Native Android companion app (user-facing name: J.A.R.V.I.S.)
- WebSocket client for the existing J.A.R.V.I.S. desktop gateway
  (keeps the internal `com.brahma.connect` package and `_BRAHMA._tcp`
  discovery identifiers for compatibility with the established trust system)
- Minimal pairing and reconnect flow with encrypted device credentials
- Live animated reactor + status, chat relay, About and Settings

What this project is not:
- Not an AI assistant (AI/Ollama/OmniRoute/OpenRouter routing stays on the PC gateway)
- Not a second dashboard (phone screen is adapted, not a desktop clone)
- Not a cloud service
- Not a Windows or Companion build

Build requirements:
- Android Studio or Android Gradle Plugin toolchain
- JDK 17
- Android SDK 35

Phase scope:
- Gateway discovery
- QR pairing
- Secure credential storage
- Persistent WebSocket connection
- Battery, flashlight, launch app, open URL, and volume commands
