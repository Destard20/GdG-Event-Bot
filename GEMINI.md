# GdG-Event-Bot - Technical Specification & Architecture Guide

## Table of Contents
- [1. Project Overview](#1-project-overview)
- [2. End-to-End Workflows](#2-end-to-end-workflows)
  - [2.1. Event Ingestion & Interception](#21-event-ingestion--interception)
  - [2.2. AI Parsing (`core/ai_parser.py`)](#22-ai-parsing-coreai_parserpy)
  - [2.3. Admin Review & Approval (`bot/callbacks.py`)](#23-admin-review--approval-botcallbackspy)
  - [2.4. Interactive Live Booking System](#24-interactive-live-booking-system)
  - [2.5. Cancellation System](#25-cancellation-system)
  - [2.6. Daily Recap Generation (`core/scheduler.py` & `bot/handlers.py`)](#26-daily-recap-generation-coreschedulerpy--bothandlerspy)
  - [2.7. Post-Recap WordPress & Story Pipeline (`bot/callbacks.py`)](#27-post-recap-wordpress--story-pipeline-botcallbackspy)
  - [2.8. Nightly Image Archiving (`core/scheduler.py` & `unzip_images.py`)](#28-nightly-image-archiving-coreschedulerpy--unzip_imagespy)
- [3. Directory Structure](#3-directory-structure)
- [4. Database Schema (SQLite: `bot_database.db`)](#4-database-schema-sqlite-bot_databasedb)
- [5. Environment Variables (`.environments`)](#5-environment-variables-environments)
- [6. Templates & Character Limit Handling](#6-templates--character-limit-handling)
- [7. Instagram Story Publishing Status & Unpause Guide](#7-instagram-story-publishing-status--unpause-guide)

---

## 1. Project Overview
**GdG-Event-Bot** is a continuously running Python application designed for **Gilda del Grifone**, a tabletop games association based in Turin (Italy).

The system automates the ingestion, standardization, social sharing, and booking management of tabletop gaming events:
- Intercepts and parses unstructured event announcements from a Telegram public channel or admin chat using Google Gemini AI.
- Re-publishes standardized event announcements to the public channel with interactive inline buttons for live seat reservations.
- Tracks reservations per user and manages seat availability in real time.
- Compiles daily recap messages and multi-image collages on game days (Mon, Wed, Fri, Sat, Sun).
- Generates Instagram Story images (1080x1920) for both individual events and daily recaps using Pillow.
- Generates engaging recap articles using Gemini AI and drafts/publishes them on WordPress via the WordPress REST API.

---

## 2. End-to-End Workflows

### 2.1. Event Ingestion & Interception
1. **Public Channel Interception (`bot/handlers.py`):**
   - The bot listens to `PUBLIC_CHANNEL_ID`.
   - When an admin posts a message with text and an image:
     - The bot checks if the message was sent by a bot or already contains booking callback buttons (`book_` / `unbook_`). If so, it ignores it to prevent loops.
     - If it is a new user/admin post, the bot **immediately deletes** the original unformatted message from the public channel.
     - The original image is downloaded and saved to `[DATA_DIR]/YYYY/MM/DD/` based on the event's parsed `normalized_date`.
     - The text is passed to `core/ai_parser.py`.
2. **Manual Ingestion (`/event_process` or `/ep`):**
   - An admin can send an image with text to `ADMIN_CHAT_ID` and reply `/event_process` or `/ep` (or include text in the command).
   - Operates through the identical parsing and review pipeline.
3. **Monitoring Pause / Resume (`/bot_pause`, `/bot_resume`, `/bot_status`):**
   - Admins can send `/bot_pause` in `ADMIN_CHAT_ID` to make the bot temporarily "blind" to `PUBLIC_CHANNEL_ID` (it will not intercept, parse, or delete messages from the channel).
   - Send `/bot_resume` to re-enable interception, and `/bot_status` to check the current operational state.

### 2.2. AI Parsing (`core/ai_parser.py`)
- Model configured via `GEMINI_MODEL` (default: `gemini-3.1-flash-lite`).
- Returns structured JSON:
  - `is_event` (bool): If `false`, non-event messages are ignored.
  - `title` (string): Event/Game title.
  - `date` (string): Raw Italian date string (e.g. `09 Settembre 21.00`).
  - `normalized_date` (string): Strict `DD-MM-YYYY` date for scheduling and folder organization.
  - `system` (string): Game system / genre (e.g. `Call of Cthulhu 7a Ed.`, `Board Game`).
  - `host` (string): Master/Host name or handle.
  - `seats` (string): Normalized string representing available seats (e.g. `4/4` or `0/0 Completo`).
  - `booked_seats` (int): Initialized to 0 for bot-managed seats.
  - `max_seats` (int or null): Bookable capacity matching the free seats specified at announcement time (e.g. if `Posti liberi: 4/5` or `2/4` is posted, `max_seats` is set to `4` or `2`, ignoring table totals `Y` since the bot only tracks open slots; `booked_seats` starts at 0).
    - `Posti: 2/2` or `Posti liberi: 3/3` -> `booked_seats: 0`, `max_seats: 2` or `3`.
    - `Posti liberi: 4/5` -> `booked_seats: 0`, `max_seats: 4`.
    - `Posti liberi: 2/4` -> `booked_seats: 0`, `max_seats: 2`.
    - `Posti liberi: 0/3 Completo` -> `booked_seats: 0`, `max_seats: 0`.
    - A deterministic regex safety net enforces `max_seats = free` and `booked_seats = 0` in `core/ai_parser.py`.
  - `extra_info` (string): Additional details (difficulty/beginner friendliness, format/duration/campaign, trigger warnings/disclaimers/X-Card, genres).
  - `description` (string): Event pitch/synopsis.
### 2.3. Admin Review & Approval (`bot/callbacks.py`)
- For messages intercepted and deleted from `PUBLIC_CHANNEL_ID`, the raw `original_text` of the event is sent to `ADMIN_CHAT_ID` as a separate message so admins can verify if the AI made any mistakes (omitted for manual `/event_process` or `/ep` triggers where the original message is already in `ADMIN_CHAT_ID`).
- Then, the parsed event is sent to `ADMIN_CHAT_ID` with inline keyboard buttons: `[Publish]`, `[Discard]`, `[Cancel]`.
- For privacy, the `Master/Host` field is omitted from generated Instagram Story images, but is displayed in the admin review message and the public channel post.
- **[Discard]:** Deletes the local event image, updates DB status to `discarded`, updates message to `❌ SCARTATO`.
- **[Cancel]:** Updates DB status to `cancelled`, updates message to `⚠️ ANNULLATO`.
- **[Publish]:**
  1. Generates 1080x1920 Instagram Story image using `utils/image_utils.create_story_image()` and saves it in `[DATA_DIR]/YYYY/MM/DD/`.
  2. Sends the generated story image to `ADMIN_CHAT_ID` for review *(Meta Graph API publishing is currently commented out for testing; see section 6)*.
  3. Formats the official standardized public channel post using `utils/templates.format_public_event_post()`.
  4. Posts the formatted message with the original image to `PUBLIC_CHANNEL_ID`, attaching the `[➕ Prenoto posto]` and `[➖ Tolgo prenotazione]` inline keyboard.
  5. Updates DB with the public `telegram_message_id` and `message_link`.
  6. Leaves a persistent `[Cancel]` button under the admin review message so admins can cancel the event at any future point.

### 2.4. Interactive Live Booking System
- **`[➕ Prenoto posto]` Callback (`book_<event_id>`):**
  - Verifies event is not cancelled and seats are available (`booked_seats < max_seats`).
  - Increments reservation for `(event_id, user_id, username)` in `reservations` table.
  - Increments `booked_seats` in `events` table.
  - Edits public message live: displays remaining seats (`max_seats - booked_seats / max_seats`).
  - Sends a reply in the public channel referencing the event: `✅ @username ha prenotato 1 posto!`.
- **`[➖ Tolgo prenotazione]` Callback (`unbook_<event_id>`):**
  - Verifies user has an active reservation (`seats_booked > 0`).
  - Decrements user reservation and total `booked_seats`.
  - Edits public message live to reflect freed seat.
  - Sends a reply in the public channel: `❌ @username ha liberato 1 posto!`.

### 2.5. Cancellation System
- Admins can click `[Cancel]` on any event at any time.
- Status set to `cancelled` in DB.
- Live public post is updated with `❌ [ANNULLATO]` and `🪑 Posti: 0/<max_seats> [ANNULLATO]`.
- The recap and stories represent cancelled events in red with `0/max_seats` seats available.

### 2.6. Daily Recap Generation (`core/scheduler.py` & `bot/handlers.py`)
1. **Triggering:**
   - **Automatic:** Scheduled daily at **18:00** via APScheduler. Automatically checks if today is Monday, Wednesday, Friday, Saturday, or Sunday.
   - **Manual:** Triggered via `/recap_generate` (or `/rg`) or `/recap_generate DD-MM-YYYY` / `/rg DD-MM-YYYY` (bypasses weekday check).
2. **Data Aggregation:**
   - Queries `events` table for all `approved` and `cancelled` events where `normalized_date == date_str`.
3. **Collage Assembly (`utils/image_utils.create_recap_collage`):**
   - Collects images for all matching events.
   - Resizes images to a uniform average height preserving individual aspect ratios (no distortion, no cropped borders).
   - Stitches horizontally and saves to `[DATA_DIR]/YYYY/MM/DD/recap_collage_DD-MM-YYYY.jpg`.
4. **Text Formatting (`utils/templates.format_recap_message`):**
   - Italian day names (Lunedì, Mercoledì, etc.).
   - Lists events with live available seats: `- Titolo (Sistema) : X/Y`.
   - If message length exceeds Telegram's 1024-character caption limit, automatically falls back to `SLIM_RECAP_TEMPLATE`.
5. **Approval:**
   - Sends collage + recap text to `ADMIN_CHAT_ID` with `[Publish Recap]` and `[Discard Recap]`.

### 2.7. Post-Recap WordPress & Story Pipeline (`bot/callbacks.py`)
When `[Publish Recap]` is clicked:
1. **Public Telegram Recap:** The collage + text is published to `PUBLIC_CHANNEL_ID`.
2. **Instagram Recap Story:**
   - `utils/image_utils.create_recap_story_image()` builds a 1080x1920 canvas.
   - Collage pinned at top, header `Proposte del [Data]`, bulleted event list with seats, and footer:
     `Ci vediamo alle 20:45, alla Gilda del Grifone in Via Ada Negri 8/A, Torino!`
   - Sent to `ADMIN_CHAT_ID` for review.
3. **WordPress Article Generation (`core/wordpress.py` & `core/ai_parser.py`):**
   - Uploads each individual event image to WordPress Media Library (style set to max 400x400px).
   - Uploads the recap collage as `featured_media`.
   - Calls Gemini AI with event details, links, and image URLs to write an engaging recap article in Italian.
   - Creates a WordPress post as `draft`.
   - Updates `wp_post_id` and `wp_post_url` in the database.
   - Sends editor link to `ADMIN_CHAT_ID` with inline button `[Pubblica su WordPress]`.
4. **WordPress One-Click Publish:**
   - Clicking `[Pubblica su WordPress]` changes post status from `draft` to `publish` via REST API.

### 2.8. Nightly Image Archiving (`core/scheduler.py` & `scripts/unzip_images.py`)
- Automatically runs daily at **23:59** via APScheduler.
- Checks today's folder (`[DATA_DIR]/YYYY/MM/DD/`) for images (`.jpg`, `.jpeg`, `.png`, `.webp`).
- Compresses them into `archive.zip` inside the same folder and removes the original loose image files to save disk space.
- Utility script `scripts/unzip_images.py` allows restoring images from `archive.zip` by specifying a folder, date, or date range.

---

## 3. Directory Structure

```text
GdG-Event-Bot/
├── bot/
│   ├── __init__.py
│   ├── handlers.py       # Message interceptors, command handlers (/event_process, /ep, /recap_generate, /rg)
│   ├── callbacks.py      # Inline keyboard callback handlers (publish, discard, cancel, book, unbook, wp publish)
│   └── keyboards.py      # Telegram inline keyboard layouts
├── core/
│   ├── __init__.py
│   ├── config.py         # Loads environment variables (.environments), paths, constants
│   ├── db.py             # SQLite CRUD operations for events and reservations
│   ├── ai_parser.py      # Gemini API integration: message extraction and WP article generation
│   ├── scheduler.py      # APScheduler job running daily at 18:00 for recaps
│   ├── wordpress.py      # WordPress REST API: media uploads, post drafting, and publishing
│   └── instagram.py      # Meta Graph API: container creation & story publishing
├── utils/
│   ├── __init__.py
│   ├── image_utils.py    # Pillow image manipulation: collages, story generation, date folder resolution
│   └── templates.py      # Standardized Telegram message templates (stories, channel posts, recaps)
├── scripts/              # Utility and maintenance scripts
│   ├── clean_db.py       # Utility script to wipe database tables and clean image folders
│   ├── unzip_images.py   # Utility script to extract archived images by directory or date range
│   └── test_ig.py        # Diagnostic script to test Meta Graph API tokens
├── data/                 # Default local storage for SQLite DB, fonts, and images
│   ├── Roboto-Bold.ttf
│   ├── Roboto-Regular.ttf
│   └── bot_database.db
├── .environments         # Environment configuration (secrets, tokens, IDs) - GIT IGNORED
├── .gitignore            # Git rules ignoring .environments, __pycache__, and data contents
├── requirements.txt      # Python dependencies
├── main.py               # Application entry point
├── README.md             # User and operator manual
└── GEMINI.md             # This document (technical and architectural specification)
```

---

## 4. Database Schema (SQLite: `bot_database.db`)

### Table: `events`
| Column | Type | Constraints / Default | Description |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Unique event identifier |
| `title` | TEXT | | Event / Game title |
| `date` | TEXT | | Raw extracted Italian date string |
| `normalized_date` | TEXT | | Standardized date string (`DD-MM-YYYY`) |
| `system` | TEXT | | Game system / genre |
| `host` | TEXT | | Master / Host handle or name |
| `seats` | TEXT | | Display string (e.g. `3/3` or `0/0 Completo`) |
| `booked_seats` | INTEGER | DEFAULT 0 | Count of currently reserved seats |
| `max_seats` | INTEGER | | Maximum capacity (NULL if unlimited) |
| `description` | TEXT | | Event synopsis / description |
| `extra_info` | TEXT | | Extra metadata (difficulty, warnings, format, tags) |
| `original_text` | TEXT | | Raw Telegram message text |
| `image_path` | TEXT | | Absolute or relative local path to original image |
| `status` | TEXT | | `pending`, `approved`, `discarded`, `cancelled` |
| `is_recap` | INTEGER | DEFAULT 0 | Historical flag (recaps now filter by date) |
| `message_link` | TEXT | | Link to message in public channel |
| `telegram_message_id`| INTEGER | | Telegram Message ID of published event post |
| `wp_post_id` | INTEGER | | Associated WordPress post ID |
| `wp_post_url` | TEXT | | Associated WordPress post edit/view URL |

### Table: `reservations`
| Column | Type | Constraints / Default | Description |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Unique reservation ID |
| `event_id` | INTEGER | | Foreign key referencing `events(id)` |
| `user_id` | INTEGER | | Telegram User ID of participant |
| `username` | TEXT | | Telegram username or first name |
| `seats_booked` | INTEGER | DEFAULT 0 | Number of seats booked by this user |

---

## 5. Environment Variables (`.environments`)

| Variable | Description | Example / Format |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Token provided by `@BotFather` | `123456789:ABCdef...` |
| `PUBLIC_CHANNEL_ID` | Telegram Channel ID | `-1001234567890` |
| `ADMIN_CHAT_ID` | Admin User ID or Admin Group ID | `123456789` or `-100...` |
| `GEMINI_API_KEY` | Google AI Studio API Key | `AIzaSy...` |
| `GEMINI_MODEL` | Gemini model name | `gemini-3.1-flash-lite` |
| `WP_URL` | WordPress base URL | `https://www.gildadelgrifonetorino.it` |
| `WP_USERNAME` | WordPress username | `direttivogilda` |
| `WP_APP_PASSWORD` | WordPress Application Password | `xxxx xxxx xxxx xxxx` |
| `IG_ACCESS_TOKEN` | Meta Long-Lived Graph API User Access Token | `EAA...` |
| `IG_ACCOUNT_ID` | Instagram Business Account Numeric ID | `178414...` |
| `DATA_DIR` | (Optional) Custom path for storage | `/var/gdg_data` |

---

## 6. Templates & Character Limit Handling
Defined in `utils/templates.py`:
- **Instagram Story Text:** Standardized Italian text block.
- **Public Event Post:** Standardized channel post with emoji formatting.
- **Full Recap Template:** Header + Event list + Footer.
- **Slim Recap Template (`SLIM_RECAP_TEMPLATE`):** Automatically activated if the full recap exceeds Telegram's 1024-character caption limit. Has minimal fixed headers/footers with `TODO` comments for further customization.

---

## 7. Instagram Story Publishing Status & Unpause Guide

### Current Status
- Story canvas generation with Pillow is **active and functional** (1080x1920 with top image, wrapped titles/systems, seat badges, and footer).
- In `bot/callbacks.py`, direct calls to `publish_instagram_story()` are temporarily commented out while Meta developer page linking is established. The bot sends the generated story image to `ADMIN_CHAT_ID` for preview.

### Steps to Re-enable Meta Graph API Publishing:
1. Ensure the Instagram account is converted to a Professional/Business account.
2. Link the Instagram account to a Facebook Page managed by the same account.
3. In [Meta Graph API Explorer](https://developers.facebook.com/tools/explorer/):
   - Select App -> Get User Access Token.
   - Permissions: `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`.
   - Grant access to the linked Page and IG Account.
   - Run `me/accounts?fields=instagram_business_account` to get numeric `IG_ACCOUNT_ID`.
   - Extend token in [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/) to get 60-day `IG_ACCESS_TOKEN`.
4. Update `.environments` with `IG_ACCESS_TOKEN` and `IG_ACCOUNT_ID`.
5. In `bot/callbacks.py`, uncomment the WordPress temporary upload and `publish_instagram_story()` calls in `handle_approval` and `handle_recap_approval`.
