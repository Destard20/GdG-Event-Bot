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
     - **AI Event Confirmation & Deferred Deletion:** The bot does not delete posts immediately upon arrival. The post is first evaluated by Gemini AI (`core/ai_parser.py`):
       - **If confirmed as an event (`is_event != False`):** The original raw message(s) are deleted from the public channel to avoid unformatted duplicates, and the event is routed to admin review.
       - **If not an event (`is_event == False` or unparseable):** The post is considered a general announcement, reminder, or notice and is preserved intact in the channel without deletion or database insertion.
     - **Multi-Image Media Groups (Albums 2–4 photos):** When an event arrives with multiple photos sharing a `media_group_id`, updates and message references are aggregated in memory across a 2-second silence buffer. If Gemini confirms the post is an event, all aggregated messages in the album are batch-deleted together. Once aggregated, `utils/image_utils.create_collage_from_bytes` builds a uniform horizontal collage (matching recap collage rules: uniform average height, preserved individual aspect ratios, no cropping or distortion). Only the stitched collage is saved as `event_{uuid}.jpg` in `[DATA_DIR]/YYYY/MM/DD/`; individual raw photos are never written to disk.
     - **Single Photo:** The image is downloaded and saved directly to `[DATA_DIR]/YYYY/MM/DD/event_{uuid}.jpg`.
     - The text is passed to `core/ai_parser.py`.
2. **Manual Ingestion (`/event_process` or `/ep`):**
   - An admin can send an image or multi-image album with text to `ADMIN_CHAT_ID` and reply `/event_process` or `/ep` (or include text directly in the command: `/ep <testo>`).
   - Photos/albums sent in `ADMIN_CHAT_ID` are silently cached in memory. When replying with `/ep` to any photo in an album, the bot aggregates all sibling photos of that `media_group_id`, stitches them into a horizontal collage using `utils/image_utils.create_collage_from_bytes`, and resolves text from the command, replied message, or album captions.
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
- **Quota / Credit Depletion Handling:**
  - If Google Gemini returns HTTP 429 or prepayment credits are depleted (`GeminiQuotaError`), the bot alerts admins immediately in `ADMIN_CHAT_ID`:
    ```
    🚨 Errore Gemini AI (Crediti esauriti):
    429 Your prepayment credits are depleted.
    ```
  - This alert is triggered during event parsing (`handle_event_extraction`) and recap WordPress article generation (`handle_approval`).

### 2.3. Admin Review & Approval (`bot/callbacks.py`)
- For messages intercepted and deleted from `PUBLIC_CHANNEL_ID`, the raw `original_text` of the event is sent to `ADMIN_CHAT_ID` as a separate message so admins can verify if the AI made any mistakes (omitted for manual `/event_process` or `/ep` triggers where the original message is already in `ADMIN_CHAT_ID`).
- Then, the parsed event is sent to `ADMIN_CHAT_ID` with inline keyboard buttons: `[Publish]`, `[Discard]`, `[Cancel]`, and `[👥 Gestisci Iscritti]`.
- For privacy, the `Master/Host` field is omitted from generated Instagram Story images, but is displayed in the admin review message and the public channel post.
- **[Discard]:** Deletes the local event image, permanently deletes the event and all associated reservations from SQLite database, updates message to `❌ SCARTATO` and removes inline action buttons.
- **[Cancel]:** Updates DB status to `cancelled`, updates message to `⚠️ ANNULLATO`, switches keyboard to `[♻️ Riattiva Evento]` and `[👥 Gestisci Iscritti]`, and posts a notice to `DISCUSSION_GROUP_ID` tagging all subscribers.
- **[Publish]:**
  1. Generates 1080x1920 Instagram Story image using `utils/image_utils.create_story_image()` and saves it in `[DATA_DIR]/YYYY/MM/DD/`.
  2. Sends the generated story image to `ADMIN_CHAT_ID` for review *(Meta Graph API publishing is currently commented out for testing; see section 6)*.
  3. Formats the official standardized public channel post using `utils/templates.format_public_event_post()`.
  4. Posts the formatted message with the original image to `PUBLIC_CHANNEL_ID`, attaching the `[➕ Prenoto posto]` and `[➖ Tolgo prenotazione]` inline keyboard.
  5. Updates DB with the public `telegram_message_id` and `message_link`.
  6. Leaves persistent `[❌ Annulla Evento]` and `[👥 Gestisci Iscritti]` buttons under the admin review message.

### 2.4. Public Booking & Same-Day Conflict Warnings
- **Seat Booking (`[➕ Prenoto posto]` / `book_<event_id>`):**
  - Increments seat reservation count for the user in `reservations` table.
  - Updates remaining seat counter on the public channel post and discussion message.
  - Posts a booking confirmation notification to `DISCUSSION_GROUP_ID` (e.g. `✅ @user ha prenotato 1 posto per: <b>Titolo</b>`, where the bold title is hyperlinked to the event post if available).
- **Same-Day Conflict Warnings (`get_user_conflicting_events` & `send_conflict_warning`):**
  - When a user reserves a seat, the system checks whether the user already holds active reservations (`seats_booked > 0`) for any other valid events (`status NOT IN ('cancelled', 'discarded')`) scheduled on that exact same day.
  - Handles date comparison across date formats (`DD-MM-YYYY` vs `YYYY-MM-DD`).
  - If conflicting events are detected, the subscription is **still processed normally**, and a formatted warning message is immediately sent to `DISCUSSION_GROUP_ID` tagging the user:
    - Informs them they are already registered for other event(s) on that day.
    - Lists all conflicting events with their bold titles (hyperlinked to the respective posts if available) and systems.
    - Advises the user to release their seat from whichever event they decide not to attend.
- **Seat Release (`[➖ Tolgo prenotazione]` / `unbook_<event_id>`):**
  - Decrements seat reservation count or deletes reservation record if 0 seats remain.
  - Updates remaining seats on public channel post and discussion message.
  - Posts a release notification to `DISCUSSION_GROUP_ID` (e.g. `❌ @user ha liberato 1 posto per: <b>Titolo</b>`, where the bold title is hyperlinked to the event post if available).

### 2.5. Admin Subscriber Management
- **`[👥 Gestisci Iscritti]` Button (`manage_subs_<event_id>`):**
  - Displays event status, total booked seats vs max seats, and a detailed list of all subscribers and their seat counts.
  - Generates inline buttons for each subscriber: `[➖ @user (N)]` and `[➕ @user (N)]` to quickly increment or decrement seats.
  - Includes a `[➕ Aggiungi Iscritto]` button that sends a `ForceReply` prompt allowing admins to register any user by typing their `@username` (with optional seat count).
  - Includes `[🔄 Aggiorna]` and `[❌ Chiudi]` buttons.
- **Commands:**
  - `/event_sub_add <event_id> @username [posti]` - also works in reply to an event message without `<event_id>`.
  - `/event_sub_remove <event_id> @username [posti]` - also works in reply to an event message without `<event_id>`.
- **Public Group Notifications (`send_admin_action_notice` in `bot/service.py`):**
  - When an event admin adds or removes subscribers or seats for a public event, a notification is posted to `DISCUSSION_GROUP_ID` (replying to `discussion_message_id` if available).
  - Explicitly states that the action was performed by an **event admin** (`admin degli eventi`) to avoid confusion with group or server administrators, tags the target user, specifies the seat count, and formats the event name in bold hyperlinking to the event post if available.

### 2.6. Cancellation & Reactivation System
- **Cancellation (`[Cancel]` / `[❌ Annulla Evento]`):**
  - Admins can click Cancel on any event.
  - Status set to `cancelled` in DB.
  - Live public post is updated with `❌ [ANNULLATO]` and `🪑 Posti: 0/<max_seats> [ANNULLATO]`, and booking buttons are removed.
  - A notification is sent to the public discussion group (`DISCUSSION_GROUP_ID`) where all subscribed Telegram users are tagged and informed of the cancellation with the bold event title (hyperlinked to the event post if available, `disable_web_page_preview=True`). If no subscribers, sends a general cancellation notice.
  - Admin post keyboard changes to `[♻️ Riattiva Evento]` and `[👥 Gestisci Iscritti]`.
- **Reactivation (`[♻️ Riattiva Evento]`):**
  - Under a cancelled event in `ADMIN_CHAT_ID`, admins can click `[♻️ Riattiva Evento]`.
  - Status set back to `approved` in DB.
  - Live public post and discussion group message are restored with active booking buttons.
  - A notification is sent to the public discussion group (`DISCUSSION_GROUP_ID`) tagging the original subscribers to inform them that the event has been reactivated with the bold event title (hyperlinked to the event post if available, `disable_web_page_preview=True`). If no subscribers, sends a general reactivation notice.
  - Admin post keyboard switches back to `[❌ Annulla Evento]` and `[👥 Gestisci Iscritti]`.

### 2.7. Daily Recap Generation (`core/scheduler.py` & `bot/handlers.py`)
1. **Triggering:**
   - **Automatic:** Scheduled daily at **18:00** via APScheduler. Automatically checks if today is Monday, Wednesday, Friday, Saturday, or Sunday. Remains silent if no events are scheduled.
   - **Manual:** Triggered via `/recap_generate` (or `/rg`) or `/recap_generate DD-MM-YYYY` / `/rg DD-MM-YYYY` (bypasses weekday check). If no events are scheduled for today (or the target date), notifies the admin directly in `ADMIN_CHAT_ID` (`Nessun evento in programma per oggi.`) without generating an empty recap.
2. **Data Aggregation:**
   - Queries `events` table for all `approved` and `cancelled` events where `normalized_date == date_str`.
3. **Collage Assembly (`utils/image_utils.create_collage`):**
   - Collects images for all matching events.
   - Resizes images to a uniform average height preserving individual aspect ratios (no distortion, no cropped borders).
   - Stitches horizontally and saves to `[DATA_DIR]/YYYY/MM/DD/recap_collage_DD-MM-YYYY.jpg`.
4. **Text Formatting (`utils/templates.recap_generate_text` & `recap_links_text`):**
   - Italian day names (Lunedì, Mercoledì, etc.).
   - Lists events in caption with bold titles and live available seats: `- <b>Titolo</b> (Sistema) : X/Y` (or `- ❌ <b>Titolo</b> (Sistema) : X/Y [ANNULLATO]`).
   - Generates comment text `recap_links_text` listing all active events with bold hyperlinked titles: `- <a href="..."><b>Titolo</b></a> (Sistema)`.
   - If recap caption length exceeds Telegram's 1024-character caption limit, automatically falls back to slim recap format.
5. **Approval:**
   - Sends collage + recap text to `ADMIN_CHAT_ID` with `[Publish Recap]` and `[Discard Recap]`.

### 2.7. Post-Recap WordPress & Story Pipeline (`bot/callbacks.py`)
When `[Publish Recap]` is clicked:
1. **Public Telegram Recap:** The collage + text is published to `PUBLIC_CHANNEL_ID`. The links message (`recap_links_text`) is NOT posted to the public channel; it is sent exclusively as a reply to the automatic channel forward in the Discussion Chat group (`DISCUSSION_GROUP_ID`).
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
│   ├── date_utils.py     # Date parsing, format validation (DD-MM-YYYY [HH:MM]), and anomaly checks
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
- **`format_event_title_link(event)`:** Centralized title formatter ensuring all event titles across notifications and lists are HTML escaped and bolded (`<b>{escaped_title}</b>`), and hyperlinked to the event's public channel message (`<a href="{link}"><b>{escaped_title}</b></a>`) whenever a link exists.
- **Instagram Story Text:** Standardized Italian text block.
- **Public Event Post:** Standardized channel post with emoji formatting.
- **Full Recap Template (`recap_generate_text`):** Header + Event list with bold titles + Footer.
- **Recap Discussion Comment (`recap_links_text`):** Header + list of active events with bold hyperlinked titles to channel posts.
- **Slim Recap Template:** Automatically activated if the full recap exceeds Telegram's 1024-character caption limit. Has minimal fixed headers/footers.

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
