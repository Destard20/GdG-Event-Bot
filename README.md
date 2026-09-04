# GdG_Telegram_ChatToSocial

Automated social media and event management bot for **Gilda del Grifone**, a tabletop gaming association based in Turin, Italy.

This application monitors a Telegram channel, extracts event information using **Google Gemini AI**, generates standardized social media graphics (Instagram Stories, Collages), handles live seat bookings via interactive buttons, and publishes recap articles to **WordPress**.

---

## Table of Contents
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration (`.environments`)](#configuration-environments)
- [Running the Application](#running-the-application)
- [Telegram Commands & Workflow](#telegram-commands--workflow)
  - [1. New Event Flow](#1-new-event-flow)
  - [2. Live Seat Booking](#2-live-seat-booking)
  - [3. Daily Recap Flow](#3-daily-recap-flow)
  - [4. Admin Event Editing (Reply Commands)](#4-admin-event-editing-reply-commands)
  - [5. Bot Control Commands](#5-bot-control-commands)
- [Storage & Folder Structure](#storage--folder-structure)
- [Maintenance & Diagnostic Scripts](#maintenance--diagnostic-scripts)

---

## Features

- **Automated Telegram Channel Interception:** Listens to the public announcement channel. When an admin posts a game event with an image, the bot intercepts it, deletes the raw post, parses the content with Gemini AI, and routes it to an admin review chat.
- **Interactive Live Booking System:** Published events feature inline `[➕ Prenoto posto]` and `[➖ Tolgo prenotazione]` buttons. Users can reserve or release seats directly in Telegram; message text updates live to reflect remaining availability, and reply notifications are posted automatically.
- **Event Cancellation:** Admins can cancel any event at any time using a persistent `[Cancel]` button. Cancelled events update live in the channel and are flagged as `[ANNULLATO]` with zero seats in recaps and graphics.
- **Daily Recaps & Multi-Image Collages:** Automatically runs at 18:00 on gaming days (Mon, Wed, Fri, Sat, Sun) or on-demand via `/generate_recap`. Stitches event artwork into clean horizontal collages without cropping borders.
- **Instagram Story Generator:** Programmatically builds 1080x1920 Instagram Story cards for individual events and daily recaps using Pillow (handling top banner artwork, dynamic text wrapping, seat counters, and association location footers).
- **WordPress REST API Integration:** AI writes an Italian recap article embedding event details, Telegram message links, and individual event pictures (max 400x400). The recap collage is set as the featured image. Posts can be published publicly directly from Telegram.

---

## Requirements

- **Python 3.10+**
- **SQLite 3**
- Telegram Bot token (from `@BotFather`) with admin rights on your public channel
- Google Gemini API key (Google AI Studio)
- WordPress site with REST API and an Application Password enabled
- (Optional) Meta Developer Account with Instagram Graph API access

---

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Destard20/GdG_Telegram_ChatToSocial.git
   cd GdG_Telegram_ChatToSocial
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up configuration:**
   ```bash
   cp .environments.example .environments
   # Edit .environments with your tokens and credentials
   ```

---

## Configuration (`.environments`)

Create or edit the `.environments` file in the root directory:

```env
# Telegram Configuration
TELEGRAM_BOT_TOKEN=your_bot_token_here
PUBLIC_CHANNEL_ID=-100xxxxxxxxxx
ADMIN_CHAT_ID=your_admin_user_or_group_id

# Google Gemini AI Configuration
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.1-flash-lite

# WordPress REST API Configuration
WP_URL=https://www.gildadelgrifonetorino.it
WP_USERNAME=your_wp_username
WP_APP_PASSWORD=xxxx xxxx xxxx xxxx

# Instagram Graph API (Optional / Meta Developer)
IG_ACCESS_TOKEN=EAAG...
IG_ACCOUNT_ID=178414...

# Storage Configuration (Optional)
# DATA_DIR=/path/to/custom/data
```

> **Note on WordPress:** `WP_APP_PASSWORD` must be generated in WordPress Admin under **Users > Profile > Application Passwords**, not your primary login password.
>
> **Note on Telegram Channel:** The bot **must be added as an Administrator** in the public channel with permissions to read, send, and delete messages.


---

## Running the Application

Start the continuous listener and scheduler:

```bash
python3 main.py
```

---

## Telegram Commands & Workflow

### 1. New Event Flow
- **Channel Ingestion:** Admins post an announcement text with a picture to the public channel (`PUBLIC_CHANNEL_ID`).
- **Auto-Interception:** The bot immediately deletes the raw post and parses the content via Gemini.
- **Admin Review:** The parsed event is forwarded to `ADMIN_CHAT_ID` with buttons: `[Publish]`, `[Discard]`, `[Cancel]`.
- **Publishing:** Clicking `[Publish]` posts the officially formatted message with `[➕ Prenoto posto]` and `[➖ Tolgo prenotazione]` to the public channel and generates the Instagram Story graphic locally.
- **Manual Trigger:** In `ADMIN_CHAT_ID`, reply to any forwarded text/photo message with `/process_event`.

### 2. Live Seat Booking
- Users click `[➕ Prenoto posto]` on a channel post to reserve a seat.
- Clicks increment personal seat reservation count in SQLite.
- The post message dynamically updates (`Posti: X/Y` or `0/Y Completo`), and the bot sends a reply to the post announcing the reservation.
- Users click `[➖ Tolgo prenotazione]` to release reserved seats.

### 3. Daily Recap Flow
- Runs automatically at **18:00** on Mondays, Wednesdays, Fridays, Saturdays, and Sundays.
- **Manual Trigger:** Send `/generate_recap` in `ADMIN_CHAT_ID` (or `/generate_recap DD-MM-YYYY` for any target date).
- **Recap Card & Collage:** The bot generates a horizontal image collage of all scheduled games and compiles the formatted Italian recap text (using slim fallback if >1024 characters).
- **Review:** Admin reviews the collage and recap in Telegram with `[Publish Recap]` or `[Discard Recap]`.
- **Publishing:** Clicking `[Publish Recap]` sends the recap message to the public channel, renders the recap Instagram Story, uploads images to WordPress, and creates a draft blog post.
- **WordPress One-Click Live:** The bot returns the WordPress edit URL and a `[Pubblica su WordPress]` button to publish the post live immediately.

### 4. Admin Event Editing (Reply Commands)
In `ADMIN_CHAT_ID`, reply to any event announcement message (pending or already published) to update fields live in SQLite and edit the message in the channel:
- `/edit_title <Titolo>`
- `/edit_date <Data>`
- `/edit_normalized_date <DD-MM-YYYY>`
- `/edit_system <Sistema/Gioco>`
- `/edit_host <Master o Host>`
- `/edit_seats <X/Y, numero intero, oppure null>`
- `/edit_booked <numero intero>`
- `/edit_extra <Difficoltà, avvertenze, tag, oppure null per rimuovere>`
- `/edit_description <Descrizione o sinossi>`

### 5. Bot Control Commands
In `ADMIN_CHAT_ID`:
- `/pause`: Pauses public channel monitoring (bot becomes "blind" and will not intercept or delete events posted to the channel).
- `/resume`: Resumes public channel monitoring.
- `/bot_status`: Checks whether the bot is currently active or paused.

---

## Storage & Folder Structure

Images and database records are categorized by the **scheduled event date** (`YYYY/MM/DD`):

```text
data/
├── 2026/
│   └── 09/
│       └── 09/
│           ├── event_123.jpg       # Original uploaded image
│           ├── story_123.jpg       # Generated 1080x1920 Story
│           ├── recap_09-09-2026.jpg # Stitched collage
│           └── recap_story_09-09-2026.jpg # Recap Story
├── bot_database.db
├── Roboto-Bold.ttf
└── Roboto-Regular.ttf
```

---

## Maintenance & Diagnostic Scripts

- **Unzip Archived Images:**
  ```bash
  # Unzip all archives in a folder (year, month, or day):
  python3 unzip_images.py data/2026/09
  python3 unzip_images.py 2026/09

  # Unzip archives within a date range:
  python3 unzip_images.py --start 01-09-2026 --end 10-09-2026

  # Unzip for a specific date:
  python3 unzip_images.py --date 04-09-2026

  # Optionally delete the zip file after extraction:
  python3 unzip_images.py data/2026/09 --delete-zip
  ```

- **Reset Database & Clean Images:**
  ```bash
  python3 clean_db.py
  ```
  Safely truncates `events` and `reservations` tables, resets autoincrement counters, and removes generated `.jpg` files across all date folders while preserving fonts.

- **Check Meta Instagram Token:**
  ```bash
  python3 test_ig.py
  ```
  Tests connectivity and permissions of `IG_ACCESS_TOKEN` against Meta Graph API.

