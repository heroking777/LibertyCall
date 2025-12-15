# Calendly → Brevo Webhook Service

A Node.js webhook service that syncs Calendly bookings to Brevo contacts. When a booking is made for the specified event type, it automatically sets the `BOOKED_CALL` attribute to `true` on the matching Brevo contact, which stops the Brevo funnel automation.

## Setup

1. **Install dependencies:**
   ```bash
   npm install
   ```

2. **Configure environment variables:**
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` and set:
   - `BREVO_API_KEY`: Your Brevo API key
   - `TARGET_EVENT_TYPE_NAME`: The Calendly event type name to filter for (default: "Potenzialanalyse von Manuav")
   - `PORT`: Server port (default: 3000)
   - `CALENDLY_WEBHOOK_SECRET`: Optional webhook secret for verification

## Run Locally

```bash
npm start
```

For development with auto-reload:
```bash
npm run dev
```

The service will start on `http://localhost:3000` (or your configured PORT).

## Expose Endpoint (ngrok)

To receive webhooks from Calendly, you need to expose your local server:

1. **Install ngrok** (if not already installed):
   ```bash
   npm install -g ngrok
   # or download from https://ngrok.com/
   ```

2. **Start your webhook service:**
   ```bash
   npm start
   ```

3. **In another terminal, expose the service:**
   ```bash
   ngrok http 3000
   ```

4. **Copy the HTTPS URL** (e.g., `https://abc123.ngrok.io`)

5. **Configure in Calendly:**
   - Go to Calendly → Integrations → Webhooks
   - Add webhook URL: `https://abc123.ngrok.io/webhook/calendly`
   - Select events: `invitee.created` (or other relevant events)

## Testing

### Test with Sample Payload (curl)

```bash
curl -X POST http://localhost:3000/webhook/calendly \
  -H "Content-Type: application/json" \
  -d '{
    "event": "invitee.created",
    "payload": {
      "event_type": {
        "name": "Potenzialanalyse von Manuav"
      },
      "invitee": {
        "email": "test@example.com"
      }
    }
  }'
```

### Expected Response

The endpoint returns `200 OK` immediately with:
```json
{
  "received": true
}
```

Check the console logs for:
- `[WEBHOOK]` - Received webhook details
- `[SKIP]` - Event filtered out (wrong type or missing email)
- `[SUCCESS]` - Brevo contact updated successfully
- `[ERROR]` - Error updating Brevo contact

## How It Works

1. **Receives Calendly webhook** at `POST /webhook/calendly`
2. **Filters by event type** - Only processes bookings for `TARGET_EVENT_TYPE_NAME`
3. **Extracts invitee email** from the payload
4. **Updates Brevo contact** - Sets `BOOKED_CALL = true` attribute
5. **Retry logic** - Automatically retries on 5xx/429 errors with exponential backoff

## Endpoints

- `POST /webhook/calendly` - Main webhook endpoint for Calendly
- `GET /health` - Health check endpoint

## Calendly Payload Structure

The service handles various Calendly webhook payload formats:
- `payload.invitee.email`
- `invitee.email`
- `event.invitee.email`
- `payload.event_type.name`
- `event_type.name`
- `event.event_type.name`

## Brevo API

- Uses Brevo Contacts API: `PUT /v3/contacts/{email}`
- Sets attribute: `BOOKED_CALL = true`
- Includes retry logic (2 retries) for 5xx/429 responses
- Uses exponential backoff (1s, 2s, 4s)

## Logging

Each webhook logs:
- Received event type
- Extracted event name
- Extracted email
- Action taken (updated / skipped / error)

API keys are never logged for security.

## Production Notes

- The service returns `200 OK` immediately to acknowledge receipt
- Processing happens asynchronously after response
- All errors are logged but don't affect the HTTP response
- Consider adding webhook signature verification using `CALENDLY_WEBHOOK_SECRET`

