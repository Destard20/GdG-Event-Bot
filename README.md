# GdG-Event-Bot

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

- **Automated Telegram Channel Interception:** Listens to the public announcement channel. When an admin posts a message, the bot parses the content with Gemini AI. If confirmed as a bookable event, the bot deletes the raw post and routes it to an admin review chat; non-event announcements, reminders, and notices are left untouched in the channel.
- **Interactive Live Booking System & Same-Day Conflict Warnings:** Published events feature inline `[➕ Prenoto posto]` and `[➖ Tolgo prenotazione]` buttons. Users can reserve or release seats directly in Telegram; message text updates live to reflect remaining availability, and reply notifications are posted automatically. If a user reserves a seat on multiple valid events on the same day, the bot automatically warns them in chat with links to all conflicting events so they can choose which to keep.
- **Event Cancellation:** Admins can cancel any event at any time using a persistent `[Cancel]` button. Cancelled events update live in the channel and are flagged as `[ANNULLATO]` with zero seats in recaps and graphics.
- **Daily Recaps & Multi-Image Collages:** Automatically runs at 18:00 on gaming days (Mon, Wed, Fri, Sat, Sun) or on-demand via `/recap_generate`. Stitches event artwork into clean horizontal collages without cropping borders.
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
   git clone https://github.com/Destard20/GdG-Event-Bot.git
   cd GdG-Event-Bot
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
- **Deferred Auto-Interception:** The bot parses the content via Gemini AI first. If confirmed as an event, it deletes the raw post from the public channel and routes it to admin review; if it is not an event, it is preserved in the channel.
- **Admin Review:** The parsed event is forwarded to `ADMIN_CHAT_ID` with buttons: `[Publish]`, `[Discard]`, `[Cancel]`.
- **Publishing:** Clicking `[Publish]` posts the officially formatted message with `[➕ Prenoto posto]` and `[➖ Tolgo prenotazione]` to the public channel and generates the Instagram Story graphic locally.
- **Manual Trigger:** In `ADMIN_CHAT_ID`, reply to any forwarded text/photo message with `/event_process` (or shortcut `/ep`).

### 2. Live Seat Booking & Same-Day Conflict Warnings
- Users click `[➕ Prenoto posto]` on a channel post to reserve a seat.
- Clicks increment personal seat reservation count in SQLite.
- The post message dynamically updates (`Posti: X/Y` or `0/Y Completo`), and the bot sends a reply to the post announcing the reservation.
- **Same-Day Conflict Warning:** If a user reserves a seat on an event while already subscribed to another valid event (not cancelled or unsubscribed) scheduled for the same day, the bot processes the reservation normally and immediately posts a warning in the discussion chat. The warning tags the user, lists the conflicting event(s) with titles and direct message links, and reminds the user to release their seat from whichever event they decide not to attend.
- Users click `[➖ Tolgo prenotazione]` to release reserved seats.

### 3. Daily Recap Flow
- Runs automatically at **18:00** on Mondays, Wednesdays, Fridays, Saturdays, and Sundays (silent if no events are scheduled).
- **Manual Trigger:** Send `/recap_generate` (or shortcut `/rg`) in `ADMIN_CHAT_ID` (or `/recap_generate DD-MM-YYYY` / `/rg DD-MM-YYYY` for any target date). If there are no scheduled events for today (or the target date), the bot notifies the admin directly in `ADMIN_CHAT_ID` (`Nessun evento in programma per oggi.`) without generating an empty recap.
- **Recap Card & Collage:** The bot generates a horizontal image collage of all scheduled games and compiles the formatted Italian recap text (using slim fallback if >1024 characters).
- **Review:** Admin reviews the collage and recap in Telegram with `[Publish Recap]` or `[Discard Recap]`.
- **Publishing:** Clicking `[Publish Recap]` sends the recap message to the public channel, renders the recap Instagram Story, uploads images to WordPress, and creates a draft blog post.
- **WordPress One-Click Live:** The bot returns the WordPress edit URL and a `[Pubblica su WordPress]` button to publish the post live immediately.

### 4. Admin Event Editing (Reply Commands)
In `ADMIN_CHAT_ID`, reply to any event announcement message (pending or already published) to update fields live in SQLite and edit the message in the channel:
- `/event_edit_title <Titolo>`
- `/event_edit_date <DD-MM-YYYY [HH:MM] o DD/MM/YYYY [HH:MM]>` (calcola automaticamente il giorno della settimana in italiano e sincronizza sia `date` che `normalized_date`)
- `/event_edit_normalized_date <DD-MM-YYYY>`
- `/event_edit_system <Sistema/Gioco>`
- `/event_edit_host <Master o Host>`
- `/event_edit_seats <X/Y, numero intero, oppure null>`
- `/event_edit_booked <numero intero>`
- `/event_edit_extra <Difficoltà, avvertenze, tag, oppure null per rimuovere>`
- `/event_edit_description <Descrizione o sinossi>`
- `/event_edit_image` (allega una nuova foto o album in risposta alla scheda evento, oppure rispondi a una foto con `/event_edit_image <event_id>`)

*Nota sui controlli di validità della data:*
Durante l'acquisizione iniziale dell'evento da parte dell'AI, il bot esegue un controllo automatico di sanità della data: se la data rilevata è nel passato oppure c'è una discrepanza tra il giorno della settimana scritto e quello effettivo di calendario (es. "Sabato 04 Settembre 2026" quando il 4 settembre è venerdì), viene anteposto un avviso visibile (`🚨 ATTENZIONE ANOMALIE DATA`) nel messaggio di revisione admin. Correggendo la data con `/event_edit_date`, l'avviso viene automaticamente rimosso.

### 5. Admin Subscriber Management
In `ADMIN_CHAT_ID`, each event card includes a `[👥 Gestisci Iscritti]` button:
- View current subscribers and seat counts.
- `➕` and `➖` buttons per subscriber to adjust seats or remove bookings.
- `[➕ Aggiungi Iscritto]` button to register any Telegram user via username.
- Commands (send standalone or in reply to an event):
  - `/event_sub_add <event_id> @username [posti]`
  - `/event_sub_remove <event_id> @username [posti]`
- **Public Group Notifications:** Whenever an event admin adds or removes subscribers or seats for a public event (via buttons, reply prompt, or commands), a notification is sent to the public discussion group (`DISCUSSION_GROUP_ID`) specifying that the modification was performed by an **event admin** (distinguishing event admins from group/server admins) and indicating the target user and seat count.

### 6. Event Cancellation & Reactivation
- **Cancellation (`[❌ Annulla Evento]`):** Updates status to `cancelled`, removes booking buttons from channel and discussion group, and posts a notification in the public discussion group (`DISCUSSION_GROUP_ID`) tagging all subscribed users to inform them of the cancellation (or sends a general notice if there are no subscribers).
- **Reactivation (`[♻️ Riattiva Evento]`):** Under a cancelled event in `ADMIN_CHAT_ID`, admins can click `[♻️ Riattiva Evento]`. This restores status to `approved`, restores booking buttons in the public channel and discussion group, and posts a notification in the discussion group notifying the original subscribers that the event is reactivated.


### 7. Bot Control Commands
In `ADMIN_CHAT_ID`:
- `/bot_pause`: Pauses public channel monitoring (bot becomes "blind" and will not intercept or delete events posted to the channel).
- `/bot_resume`: Resumes public channel monitoring.
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

All maintenance utilities are located in the `scripts/` directory:

- **Unzip Archived Images:**
  ```bash
  # Unzip all archives in a folder (year, month, or day):
  python3 scripts/unzip_images.py data/2026/09
  python3 scripts/unzip_images.py 2026/09

  # Unzip archives within a date range:
  python3 scripts/unzip_images.py --start 01-09-2026 --end 10-09-2026

  # Unzip for a specific date:
  python3 scripts/unzip_images.py --date 04-09-2026

  # Optionally delete the zip file after extraction:
  python3 scripts/unzip_images.py data/2026/09 --delete-zip
  ```

- **Reset Database & Clean Images:**
  ```bash
  python3 scripts/clean_db.py
  ```
  Safely truncates `events` and `reservations` tables, resets autoincrement counters, and removes generated `.jpg` files across all date folders while preserving fonts.

- **Check Meta Instagram Token:**
  ```bash
  python3 scripts/test_ig.py
  ```
  Tests connectivity and permissions of `IG_ACCESS_TOKEN` against Meta Graph API.

