require('dotenv').config();
const express = require('express');
const axios = require('axios');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3000;

// Log to both console and file
const logFile = 'webhook.log';
const log = (...args) => {
  const message = args.join(' ');
  console.log(message);
  fs.appendFileSync(logFile, new Date().toISOString() + ' ' + message + '\n');
};

// Middleware
app.use(express.json());

// Brevo API configuration
const BREVO_API_BASE = 'https://api.brevo.com/v3';
const BREVO_API_KEY = process.env.BREVO_API_KEY;
const TARGET_EVENT_TYPE_NAME = process.env.TARGET_EVENT_TYPE_NAME || 'Potenzialanalyse von Manuav';
const CALENDLY_WEBHOOK_SECRET = process.env.CALENDLY_WEBHOOK_SECRET;

// Helper function to update Brevo contact with retry logic
async function updateBrevoContact(email, retries = 2) {
  const headers = {
    'api-key': BREVO_API_KEY,
    'Content-Type': 'application/json'
  };
  const data = {
    email: email,
    attributes: {
      BOOKED_CALL: true
    }
  };

  // First, try to update existing contact
  const updateUrl = `${BREVO_API_BASE}/contacts/${encodeURIComponent(email)}`;
  
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const response = await axios.put(updateUrl, data, { headers });
      return { success: true, status: response.status };
    } catch (error) {
      const status = error.response?.status;
      
      // If contact doesn't exist (404), create it
      if (status === 404) {
        try {
          const createUrl = `${BREVO_API_BASE}/contacts`;
          const createResponse = await axios.post(createUrl, data, { headers });
          return { success: true, status: createResponse.status };
        } catch (createError) {
          return {
            success: false,
            status: createError.response?.status || createError.code,
            message: createError.response?.data?.message || createError.message
          };
        }
      }
      
      const isRetryable = status >= 500 || status === 429;

      if (attempt < retries && isRetryable) {
        // Exponential backoff: 1s, 2s, 4s
        const delay = Math.pow(2, attempt) * 1000;
        await new Promise(resolve => setTimeout(resolve, delay));
        continue;
      }

      return {
        success: false,
        status: status || error.code,
        message: error.response?.data?.message || error.message
      };
    }
  }
}

// Helper function to extract email from Calendly payload
function extractEmail(payload) {
  // Calendly webhook payload structure can vary
  // Common paths: payload.invitee.email, invitee.email, event.invitee.email
  return payload?.payload?.invitee?.email ||
         payload?.invitee?.email ||
         payload?.event?.invitee?.email ||
         payload?.event?.invitee?.email_address ||
         null;
}

// Helper function to extract event type name from Calendly payload
function extractEventTypeName(payload) {
  return payload?.payload?.event_type?.name ||
         payload?.event_type?.name ||
         payload?.event?.event_type?.name ||
         payload?.event_type_name ||
         null;
}

// Helper function to extract event name (invitee.created, etc.)
function extractEventName(payload) {
  return payload?.event ||
         payload?.name ||
         payload?.event_name ||
         null;
}

// Webhook endpoint
app.post('/webhook/calendly', async (req, res) => {
  // Return 200 immediately to acknowledge receipt
  res.status(200).json({ received: true });

  const payload = req.body;
  const eventName = extractEventName(payload);
  const eventTypeName = extractEventTypeName(payload);
  const email = extractEmail(payload);

  // Log received webhook
  log(`[WEBHOOK] Received event: ${eventName || 'unknown'}, Event type: ${eventTypeName || 'unknown'}, Email: ${email || 'missing'}`);

  // Filter by event type name
  if (eventTypeName !== TARGET_EVENT_TYPE_NAME) {
    log(`[SKIP] Event type mismatch. Expected: "${TARGET_EVENT_TYPE_NAME}", Got: "${eventTypeName || 'unknown'}"`);
    return;
  }

  // Check if email exists
  if (!email) {
    log(`[SKIP] Email missing from payload`);
    return;
  }

  // Update Brevo contact
  try {
    const result = await updateBrevoContact(email);
    if (result.success) {
      log(`[SUCCESS] Updated Brevo contact: ${email} (status: ${result.status})`);
    } else {
      log(`[ERROR] Failed to update Brevo contact: ${email} (status: ${result.status}, message: ${result.message || 'unknown'})`);
    }
  } catch (error) {
    log(`[ERROR] Exception updating Brevo contact: ${email} - ${error.message}`);
  }
});

// Health check endpoint
app.get('/health', (req, res) => {
  res.status(200).json({ status: 'ok' });
});

// Start server
app.listen(PORT, () => {
  log(`Webhook service listening on port ${PORT}`);
  log(`Target event type: ${TARGET_EVENT_TYPE_NAME}`);
  if (!BREVO_API_KEY) {
    log('WARNING: BREVO_API_KEY not set');
  }
});

