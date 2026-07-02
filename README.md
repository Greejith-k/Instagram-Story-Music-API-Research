# Instagram Story Music API Research

> **Educational research project** demonstrating how the Instagram Story Music feature retrieves and plays music.

## Overview

This project documents the network workflow behind Instagram's Story Music feature. By analyzing browser network traffic, I identified the sequence of API requests used to search for music, retrieve audio metadata, and obtain the media stream used for playback.

The objective of this research is to understand modern web application architecture, API communication, and CDN-based media delivery.

---

## Workflow

### 1. Search for a Song

The first request searches the music catalog using a keyword.

```
GET /api/v1/mscr/tracks?q=<song_name>
```

Example:

```
GET /api/v1/mscr/tracks?q=kannu
```
<img width="1920" height="1040" alt="1" src="https://github.com/user-attachments/assets/bb293061-48b9-489b-a8fe-40791b8f47c6" />

This endpoint returns a list of matching tracks along with metadata, including the audio asset identifier required for the next step.

---

### 2. Request Music Metadata

After selecting a song, the client sends a POST request to retrieve additional information about the selected audio asset.

```
POST /api/v1/clips/music/
```
<img width="1920" height="1040" alt="2" src="https://github.com/user-attachments/assets/138baa34-8d3b-4e31-9346-78f6647b8c41" />

This request requires:

* A valid authenticated Instagram session (`sessionid` cookie)
* A valid CSRF token (`fb_dtsg`)
* The selected `original_sound_audio_asset_id`

Without a valid authenticated session and CSRF token, this request will not succeed.

---

### 3. Retrieve the Media Stream

The response from the previous request includes a CDN-hosted media URL.

The browser then requests the media directly from Instagram's CDN.

```
GET https://instagram...cdn.../audio.mp4
```
<img width="1920" height="1040" alt="3" src="https://github.com/user-attachments/assets/b860e412-9386-4707-9fc7-df8161dac3dd" />

The returned URL is used by the Instagram client for audio playback.

---
<img width="983" height="977" alt="4" src="https://github.com/user-attachments/assets/63a9240e-e3b2-4f1d-b4d0-4e5741ee6af0" />

## Request Flow

```
User Search
      │
      ▼
Search API
      │
      ▼
Track List
      │
Select Song
      │
      ▼
Music Metadata API
(Session Cookie + CSRF Required)
      │
      ▼
CDN Media URL
      │
      ▼
Audio Playback
```

---

## What I Learned

* Browser network traffic analysis
* Reverse engineering client-side workflows
* HTTP request sequencing
* Session-based authentication
* CSRF protection
* Media delivery through CDN infrastructure
* API automation techniques

---

## Disclaimer

This repository is intended solely for educational and research purposes.

The documented requests originate from the normal operation of the Instagram web client. This project does **not** include methods for bypassing authentication, authorization, licensing, or other platform security controls.

Please respect Instagram's Terms of Service and applicable copyright laws when conducting similar research.

---

## Author

**Greejith K**

Cybersecurity Researcher | Web Security | Reverse Engineering | API Analysis | IoT Security
