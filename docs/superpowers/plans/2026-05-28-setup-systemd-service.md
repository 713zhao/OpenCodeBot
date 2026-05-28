# Configure ClaudeCodeBot Systemd Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configure systemd user service for ClaudeCodeBot to auto-start on boot and auto-restart on failure.

**Architecture:** We will modify the existing `opencodebot.service` file in the user's systemd directory (`~/.config/systemd/user/opencodebot.service`) to point to the active `ClaudeCodeBot` workspace path and its correct virtual environment (`venv`). We will then reload systemd, enable the service for boot persistence, and start it.

**Tech Stack:** systemd, bash

---

### Task 1: Update systemd service configuration

**Files:**
- Modify: `/home/eric/.config/systemd/user/opencodebot.service`

- [ ] **Step 1: Read current systemd service configuration**
  Read the file to make sure we modify it correctly. (We've read it via bash, but let's read the file directly if needed.)

- [ ] **Step 2: Modify service file content**
  Update paths to point to `/home/eric/.openclaw/workspace/ClaudeCodeBot` instead of `/home/eric/.openclaw/workspace/OpenCodeBot`.
  Ensure `Restart=always` and `RestartSec=5` are correctly set up.

---

### Task 2: Apply and enable service changes

- [ ] **Step 1: Reload systemd configuration daemon**
  Run `systemctl --user daemon-reload` to load the changes.

- [ ] **Step 2: Stop any active background nohup instances of the bot**
  Make sure our previous `nohup` manual instance from `start.sh` is terminated to prevent port/token binding conflicts.

- [ ] **Step 3: Enable the systemd user service**
  Run `systemctl --user enable opencodebot.service` so that it starts automatically on system boot.

- [ ] **Step 4: Enable lingering for user 'eric'**
  Ensure that user services start automatically at system boot without needing an active SSH/GUI session by running `sudo loginctl enable-linger eric`.

---

### Task 3: Start and verify the service

- [ ] **Step 1: Start the systemd service**
  Run `systemctl --user start opencodebot.service`.

- [ ] **Step 2: Check service status and logs**
  Run `systemctl --user status opencodebot.service` and examine the journal logs with `journalctl --user -u opencodebot.service -n 20` to verify successful connection and polling.

- [ ] **Step 3: Test auto-restart on failure**
  Kill the active python process to verify systemd automatically restarts it.
