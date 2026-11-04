# Almero web UI

An accessible meeting room for Deaf and hearing colleagues, with a built-in interpreter.

## Run it
```
npm install
npm run dev
```
Open `http://localhost:5173`. With no `VITE_SERVICE_URL` set, it runs on a fake backend: a Sam or Alice bot joins you.

- **Presenter controls:** press **D** in the room (or tap the logo five times on a phone). Never shown to the audience.
- **One-laptop backup:** open `/?split=1`, then press Join now on both sides. Two windows in the same browser with the same room code also share a room.

## Connect the real service
Copy `.env.example` to `.env`, remove `VITE_MOCK=1` and set `VITE_SERVICE_URL=ws://<laptop-ip>:8000/ws`. Messages are in `../docs/meeting-room-contract.md`.

**Run the page on each laptop.** Browsers only allow the camera and mic on `https://` or `localhost`, so opening another laptop's `http://` address won't work. Everyone's page connects to the one service.

## What needs internet
- Hand tracking's model file downloads the first time.
- Browser speech to text sends audio to the browser maker's servers.

## Change the avatar
Replace `public/models/interpreter.vrm` with any VRM humanoid (VRM 1.0 from VRoid Studio).

## Honest limits
- The avatar's signs are **placeholder movements**, not checked BSL. Replace them in `src/avatar/signs.ts`, ideally with a Deaf BSL signer.
- On the fake backend, only signs taught in Add a sign are really recognised from the webcam. The presenter buttons stand in for the rest.
