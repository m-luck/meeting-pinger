# Encrypted Video Sharing System - Architecture Plan

## Overview

P2P WebRTC system supporting screen sharing, system audio, microphone, and bidirectional voice. E2E encrypted by default. Designed for small rooms (2-6 participants).

---

## Architecture

### Component Split

| Component | Host | Role |
|---|---|---|
| Signaling server | Render (starter, $7/mo) | WebSocket server for SDP/ICE exchange |
| STUN | Google public servers | NAT traversal (free) |
| Media transport | Browser-to-browser (P2P) | No server in the media path |

### Why P2P

- E2E encryption for free (SRTP between browsers, no middleman)
- No media server to provision or pay for
- Render only handles signaling (tiny JSON messages over WebSocket)
- Works well for rooms up to 4-6 participants

### When P2P Breaks Down

- Screen share at 1080p (~3 Mbps) is uploaded once per viewer
- At 6 viewers: ~18 Mbps upload from the sharer alone
- WebRTC will degrade resolution/framerate to compensate
- Beyond 6 viewers: need an SFU (see "Scaling" section below)

---

## Client-Side Implementation

### Stream Capture

```typescript
// Screen + system audio (Chromium only for system audio)
const screenStream = await navigator.mediaDevices.getDisplayMedia({
  video: true,
  audio: true, // captures system/tab audio
})

// Microphone
const micStream = await navigator.mediaDevices.getUserMedia({
  audio: true,
})
```

### Peer Connection Setup

```typescript
const config: RTCConfiguration = {
  iceServers: [
    { urls: "stun:stun.l.google.com:19302" },
    { urls: "stun:stun1.l.google.com:19302" },
  ],
}

const pc = new RTCPeerConnection(config)

// Add all tracks to the connection
screenStream.getTracks().forEach(track => pc.addTrack(track, screenStream))
micStream.getAudioTracks().forEach(track => pc.addTrack(track, micStream))

// Handle incoming tracks from the remote peer
pc.ontrack = (event) => {
  // event.streams[0] contains the remote peer's media
  // Attach to <video> or <audio> elements
}
```

### Signaling Flow (via WebSocket to Render server)

```
Alice                    Render (signaling)              Bob
  |                           |                           |
  |-- join room ------------->|                           |
  |                           |<---------- join room -----|
  |                           |                           |
  |-- SDP offer ------------->|                           |
  |                           |---------- SDP offer ----->|
  |                           |                           |
  |                           |<--------- SDP answer -----|
  |<-- SDP answer ------------|                           |
  |                           |                           |
  |-- ICE candidates -------->|                           |
  |                           |------ ICE candidates ---->|
  |                           |                           |
  |                           |<----- ICE candidates -----|
  |<-- ICE candidates --------|                           |
  |                           |                           |
  |<============ P2P media (direct, encrypted) ==========>|
  |            (Render is no longer involved)              |
```

---

## Signaling Server (Render)

Lightweight WebSocket server. No media processing.

### Responsibilities

- Room management (join/leave)
- Relay SDP offers/answers between peers
- Relay ICE candidates between peers
- Optionally: room presence, user lists

### Implementation Sketch

```typescript
// Node.js + ws library
import { WebSocketServer } from "ws"

const rooms = new Map<string, Set<WebSocket>>()

wss.on("connection", (ws) => {
  ws.on("message", (raw) => {
    const msg = JSON.parse(raw)

    switch (msg.type) {
      case "join":
        // Add to room, notify others
        break
      case "offer":
      case "answer":
      case "ice-candidate":
        // Forward to target peer in the room
        break
      case "leave":
        // Remove from room, notify others
        break
    }
  })
})
```

### Render Starter Capacity for Signaling

- ~2,000-5,000 concurrent WebSocket connections
- ~1,000+ concurrent rooms (2-person)
- CPU and bandwidth are negligible for JSON relay
- Bottleneck is memory from open connections (~50-200 KB each)

---

## Encryption

### Default: SRTP (automatic in P2P WebRTC)

- All media encrypted between browsers via SRTP
- Keys exchanged via DTLS handshake during connection setup
- Signaling server never has access to media or keys
- True E2E encryption with no additional implementation needed

### Optional: Insertable Streams (if SFU is added later)

If you move to an SFU, the server can read RTP headers. To maintain E2E encryption through an SFU:

```typescript
// Encrypt frame payload before it reaches the transport
const senderTransform = new TransformStream({
  transform(frame, controller) {
    const encrypted = encrypt(frame.data, sharedKey)
    controller.enqueue(new EncodedVideoFrame(encrypted, frame))
  },
})

const sender = pc.addTrack(track)
const senderStreams = sender.createEncodedStreams()
senderStreams.readable
  .pipeThrough(senderTransform)
  .pipeTo(senderStreams.writable)
```

- Chromium-only (Insertable Streams API)
- ~2-5% additional CPU per client for video
- Key rotation on join/leave: generate new AES key, distribute via signaling channel
- For 4-6 participants, simple key distribution is fine (no MLS/DAVE needed)

---

## Post-Quantum Consideration (PQXDH)

For future-proofing the signaling key exchange against quantum attacks:

### What It Adds

- ML-KEM (Kyber) key encapsulation layered on top of classical X25519 DH
- If quantum computers break X25519, ML-KEM still protects
- If ML-KEM has a flaw, X25519 still protects (belt and suspenders)

### Libraries

```typescript
// @noble/post-quantum for ML-KEM
import { ml_kem768 } from "@noble/post-quantum/ml-kem"
// @noble/curves for X25519
import { x25519 } from "@noble/curves/ed25519"
// @noble/hashes for key derivation
import { hkdf } from "@noble/hashes/hkdf"
```

### When to Implement

- Not needed for MVP
- WebRTC's built-in DTLS/SRTP is sufficient today
- Add when post-quantum TLS becomes standard or if handling sensitive content
- The signaling channel (WebSocket over TLS) is the main harvest-now-decrypt-later surface

---

## Bandwidth Budget

### Per Participant Upload

| Stream | Bitrate |
|---|---|
| Screen share (1080p) | 2-4 Mbps |
| Screen share (720p, degraded) | 1-2 Mbps |
| Microphone (Opus) | 32-64 kbps |
| System audio (Opus) | 64-128 kbps |

### Total Upload by Room Size (screen sharer's perspective)

| Viewers | Upload Required | Typical Home Internet | Feasible? |
|---|---|---|---|
| 1 | ~3.1 Mbps | 10-20 Mbps up | Yes |
| 2 | ~6.2 Mbps | 10-20 Mbps up | Yes |
| 3 | ~9.3 Mbps | 10-20 Mbps up | Marginal |
| 5 | ~15.5 Mbps | 10-20 Mbps up | Degraded quality |
| 6+ | ~18.6+ Mbps | 10-20 Mbps up | Needs SFU |

### Per Viewer Download

~3.4 Mbps (1 video stream + all audio streams). Download is rarely the bottleneck.

---

## Scaling Path (When P2P Isn't Enough)

### Add an SFU

When rooms exceed 4-6 people, add a LiveKit server:

| Component | Host | Cost |
|---|---|---|
| Signaling + app logic | Render (starter) | $7/mo |
| LiveKit SFU | Hetzner CAX21 (4 ARM cores, 8GB) | ~$7/mo |

- Sharer uploads once regardless of viewer count
- SFU handles fan-out
- Add Insertable Streams for E2E encryption through the SFU
- UDP support on the VPS (which Render lacks)

### Why Not SFU on Render

- Render doesn't expose UDP ports
- Media would be forced through TCP, causing head-of-line blocking
- Audio stuttering and video freezes under any packet loss
- Even large Render instances have this protocol limitation

---

## Implementation Phases

### Phase 1: Voice Chat (P2P)

- WebSocket signaling server on Render
- getUserMedia for microphone
- P2P WebRTC connections between room members
- Room join/leave management
- SRTP encryption (automatic)

### Phase 2: Screen Sharing

- Add getDisplayMedia with video + system audio
- Multiple tracks per peer connection
- UI for selecting which screen/window to share
- Handle screen share start/stop events

### Phase 3: E2E Encryption Hardening (Optional)

- Insertable Streams for frame-level encryption
- Key rotation on participant join/leave
- Key distribution over signaling WebSocket

### Phase 4: SFU for Larger Rooms (Optional)

- Deploy LiveKit on a VPS
- Route media through SFU when room size > 4
- Maintain P2P for small rooms
- Insertable Streams for E2E encryption through SFU

### Phase 5: Post-Quantum Key Exchange (Optional)

- PQXDH for signaling channel key agreement
- ML-KEM + X25519 hybrid approach
- @noble/post-quantum library integration

---

## Tech Stack Summary

| Layer | Technology |
|---|---|
| Signaling transport | WebSocket (ws or Socket.IO) |
| Signaling host | Render starter ($7/mo) |
| Media transport | WebRTC (browser-native) |
| Video codec | VP8/VP9/H.264 (browser-negotiated) |
| Audio codec | Opus |
| Encryption | SRTP (default), Insertable Streams (optional) |
| NAT traversal | Google public STUN servers |
| SFU (if needed) | LiveKit on Hetzner VPS |
| Post-quantum (if needed) | ML-KEM via @noble/post-quantum |
