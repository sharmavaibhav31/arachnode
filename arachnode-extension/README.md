# Arachnode Referrals — Chrome/Edge Extension

Sends your daily LinkedIn outreach queue without the copy-paste.
You always review and click Send yourself.

## Setup

1. Make sure Arachnode is running locally (docker compose up)
2. Open chrome://extensions or edge://extensions
3. Enable Developer Mode (top right toggle)
4. Click "Load unpacked"
5. Select this arachnode-extension/ folder
6. Click the extension icon in your toolbar
7. Enter your gateway URL (default: http://localhost:8080)
8. Click Save & Connect

## How to use it

1. Open the extension — it shows today's queue
2. Click a contact to start
3. The extension opens their LinkedIn profile in a new tab
4. The message box is pre-filled with your personalized draft
5. Read the message, edit if you want, click Send on LinkedIn
6. Come back to the extension, click "Sent — Next Contact"
7. Repeat

## Sending limit

The queue pulls from your configured daily limit (default: 20).
Change REFERRAL_DAILY_LIMIT in your .env to adjust.

## The extension never:
- Clicks the Send button on LinkedIn
- Submits any form
- Stores your LinkedIn credentials
- Sends data anywhere except your local Arachnode instance

## Troubleshooting

Message box not filling?
  Click the Message button on LinkedIn first, 
  then the extension will detect it and fill automatically.

Extension can't reach Arachnode?
  Make sure docker compose up is running and 
  http://localhost:8080/api/health returns 200.
