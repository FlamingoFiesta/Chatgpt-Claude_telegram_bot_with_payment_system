import os
import sys
from pathlib import Path

bot_dir = Path(__file__).parent.parent / "bot"
sys.path.append(str(bot_dir))
#import yaml
from flask import Flask, request, jsonify
import stripe
from telegram import Bot
import config
from database import Database


db = Database()
app = Flask(__name__)
bot = Bot(token=config.telegram_token)

stripe.api_key = config.stripe_secret_key
STRIPE_WEBHOOK_SECRET = config.stripe_webhook_secret

@app.route('/stripe-webhook', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError as e:
        return 'Invalid signature', 400

    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = int(session['metadata']['user_id'])
        is_donation = session['metadata'].get('is_donation', 'false') == 'true'

        total_amount_paid_cents = session['amount_total']  # Total amount paid by the user in cents
        total_amount_paid_euros = total_amount_paid_cents / 100.0  # Convert to euros

        net_euro_amount = total_amount_paid_euros

        if not is_donation:

            if total_amount_paid_cents == 125:  # User chose the 1 euro (and 25 cent option)
                net_euro_amount = 1.0  # User gets 1 euro added to their balance, absorbing the 25 cent tax
            else:
            # For all other options, absorb the Stripe tax completely
                net_euro_amount = total_amount_paid_euros

            db.update_euro_balance(user_id, net_euro_amount)

        else:
            net_euro_amount = total_amount_paid_euros


        send_confirmation_message(user_id, net_euro_amount, is_donation)
    return jsonify({'status': 'success'}), 200


import redis
import json

def send_confirmation_message(user_id, euro_amount, is_donation):
    redis_client = redis.Redis(host='redis', port=6379, db=0)
    data = {
        'user_id': user_id,
        'euro_amount': euro_amount,
        'is_donation': is_donation
    }
    redis_client.publish('payment_notifications', json.dumps(data))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)