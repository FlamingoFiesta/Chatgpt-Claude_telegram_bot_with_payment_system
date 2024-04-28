from typing import Optional, Any

import pymongo
import uuid
from datetime import datetime

import config


class Database:
    def __init__(self):
        self.client = pymongo.MongoClient(config.mongodb_uri)
        self.db = self.client["chatgpt_telegram_bot"]

        self.user_collection = self.db["user"]
        self.dialog_collection = self.db["dialog"]

    def check_if_user_exists(self, user_id: int, raise_exception: bool = False):
        if self.user_collection.count_documents({"_id": user_id}) > 0:
            return True
        else:
            if raise_exception:
                raise ValueError(f"User {user_id} does not exist")
            else:
                return False

    def add_new_user(
        self,
        user_id: int,
        chat_id: int,
        username: str = "",
        first_name: str = "",
        last_name: str = "",
    ):
        user_dict = {
            "_id": user_id,
            "chat_id": chat_id,

            "username": username,
            "first_name": first_name,
            "last_name": last_name,

            "last_interaction": datetime.now(),
            "first_seen": datetime.now(),

            "current_dialog_id": None,
            "current_chat_mode": "cyberdud",
            "current_model": config.models["available_text_models"][2],

            "n_used_tokens": {},

            "n_generated_images": 0,
            "n_transcribed_seconds": 0.0,  # voice message transcription
            "token_balance": 1000,  # Initialize token balance for new users
            "persona": "trial_user",
            "euro_balance": 1
        }

        if not self.check_if_user_exists(user_id):
            self.user_collection.insert_one(user_dict)

    def start_new_dialog(self, user_id: int):
        self.check_if_user_exists(user_id, raise_exception=True)

        dialog_id = str(uuid.uuid4())
        dialog_dict = {
            "_id": dialog_id,
            "user_id": user_id,
            "chat_mode": self.get_user_attribute(user_id, "current_chat_mode"),
            "start_time": datetime.now(),
            "model": self.get_user_attribute(user_id, "current_model"),
            "messages": []
        }

        # add new dialog
        self.dialog_collection.insert_one(dialog_dict)

        # update user's current dialog
        self.user_collection.update_one(
            {"_id": user_id},
            {"$set": {"current_dialog_id": dialog_id}}
        )

        return dialog_id

    def get_user_attribute(self, user_id: int, key: str):
        self.check_if_user_exists(user_id, raise_exception=True)
        user_dict = self.user_collection.find_one({"_id": user_id})

        if key not in user_dict:
            return None

        return user_dict[key]

    def set_user_attribute(self, user_id: int, key: str, value: Any):
        self.check_if_user_exists(user_id, raise_exception=True)
        self.user_collection.update_one({"_id": user_id}, {"$set": {key: value}})

    def update_n_used_tokens(self, user_id: int, model: str, n_input_tokens: int, n_output_tokens: int):
        n_used_tokens_dict = self.get_user_attribute(user_id, "n_used_tokens")

        if model in n_used_tokens_dict:
            n_used_tokens_dict[model]["n_input_tokens"] += n_input_tokens
            n_used_tokens_dict[model]["n_output_tokens"] += n_output_tokens
        else:
            n_used_tokens_dict[model] = {
                "n_input_tokens": n_input_tokens,
                "n_output_tokens": n_output_tokens
            }

        self.set_user_attribute(user_id, "n_used_tokens", n_used_tokens_dict)

    def get_dialog_messages(self, user_id: int, dialog_id: Optional[str] = None):
        self.check_if_user_exists(user_id, raise_exception=True)

        if dialog_id is None:
            dialog_id = self.get_user_attribute(user_id, "current_dialog_id")

        dialog_dict = self.dialog_collection.find_one({"_id": dialog_id, "user_id": user_id})
        return dialog_dict["messages"]

    def set_dialog_messages(self, user_id: int, dialog_messages: list, dialog_id: Optional[str] = None):
        self.check_if_user_exists(user_id, raise_exception=True)

        if dialog_id is None:
            dialog_id = self.get_user_attribute(user_id, "current_dialog_id")

        self.dialog_collection.update_one(
            {"_id": dialog_id, "user_id": user_id},
            {"$set": {"messages": dialog_messages}}
        )
    
    #new additions, they work tho
    def check_token_balance(self, user_id: int) -> int:
        """Check the user's current token balance."""
        user = self.user_collection.find_one({"_id": user_id})
        return user.get("token_balance", 0)


    def deduct_tokens_based_on_persona(self, user_id: int, n_input_tokens: int, n_output_tokens: int):
        user = self.user_collection.find_one({"_id": user_id})
        persona = user.get("persona", "Trial_User")  # Default to Trial_User if not set
        deduction_rate = config.persona_deduction_rates.get(persona, 1)  # Use the rates from config.py
        tokens_to_deduct = (n_input_tokens + n_output_tokens) * deduction_rate
        self.user_collection.update_one(
            {"_id": user_id},
            {"$inc": {"token_balance": -tokens_to_deduct}}
        )

    def get_user_persona(self, user_id: int) -> str:
        """Determine the persona of a user based on their user ID."""
        user = self.user_collection.find_one({"_id": user_id})
        if user and "persona" in user:
            return user["persona"]
        return "Trial_User"  # Default persona if not explicitly set

    def get_user_count(self):
        return self.user_collection.count_documents({})
    
    def get_users_and_personas(self):
    # Fetch all users and project only the first_name and persona
        users_cursor = self.user_collection.find({}, {"username": 1,"first_name": 1, "persona": 1})
        return list(users_cursor)
    
    def find_users_by_persona(self, persona: str):
        return list(self.user_collection.find({"persona": persona}))

    def find_user_by_username(self, username: str):
        return self.user_collection.find_one({"username": username})

    def find_users_by_first_name(self, first_name: str):
        return list(self.user_collection.find({"first_name": first_name}))    

    def update_euro_balance(self, user_id: int, euro_amount: float):
        self.check_if_user_exists(user_id, raise_exception=True)
        self.user_collection.update_one(
            {"_id": user_id},
            {"$inc": {"euro_balance": euro_amount}}
        )

    def get_user_euro_balance(self, user_id: int) -> float:
    
        user = self.user_collection.find_one({"_id": user_id})
        return user.get("euro_balance", 0.0)

    def deduct_euro_balance(self, user_id: int, euro_amount: float):
        self.check_if_user_exists(user_id, raise_exception=True)
    # Ensure the deduction amount is not negative to avoid accidental balance increase
        if euro_amount < 0:
            raise ValueError("Deduction amount must be positive")
        self.user_collection.update_one(
            {"_id": user_id},
            {"$inc": {"euro_balance": -euro_amount}}
        )

    def deduct_cost_for_action(self, user_id: int, action_type: str, action_params: dict):
        user_persona = self.get_user_persona(user_id)
        deduction_rate = config.persona_deduction_rates.get(user_persona, 1)

        if action_type in ['gpt-3.5-turbo', 'gpt-3.5-turbo-16k', 'gpt-4', 'gpt-4-1106-preview', 'gpt-4-vision-preview', 'text-davinci-003']:
            # For text models, price is per 1000 tokens
            total_tokens = action_params.get('n_input_tokens', 0) + action_params.get('n_output_tokens', 0)
            adjusted_tokens = total_tokens * deduction_rate
            price_per_1000_tokens_in_euros = config.model_pricing[action_type]
            cost_in_euros = (adjusted_tokens / 1000) * price_per_1000_tokens_in_euros

        elif action_type == 'dalle-2':
            # For DALLE, price is per image
            n_images = action_params.get('n_images', 1)
            cost_in_euros = n_images * config.model_pricing[action_type] * deduction_rate
            #print(f"Action Type: {action_type}, Deduction Rate: {deduction_rate}, N Images: {n_images}, Cost in Euros: {cost_in_euros}")

        elif action_type == 'whisper':
            # For Whisper, price is per minute
            audio_duration_minutes = action_params.get('audio_duration_minutes', 0)
            cost_in_euros = audio_duration_minutes * config.model_pricing[action_type] * deduction_rate

        else:
            raise ValueError(f"Unknown action type: {action_type}")

        self.deduct_euro_balance(user_id, cost_in_euros)

