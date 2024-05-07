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
            "image_preferences": {
                "model": config.models["available_image_models"][0],
                "quality": "standard",
                "resolution": "1024x1024",
                "n_images": 1
            },

            "n_used_tokens": {},
            "total_spent": 0,
            "dalle_2": {"images": 0, "cost": 0.0},
            "dalle_3": {"images": 0, "cost": 0.0},
            "n_generated_images": 0,
            "n_transcribed_seconds": 0.0,  # voice message transcription
            "token_balance": 100000,  # Initialize token balance for new users
            "role": "trial_user",
            "euro_balance": 1,
            "total_topup": 0,
            "total_donated": 0
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


    def deduct_tokens_based_on_role(self, user_id: int, n_input_tokens: int, n_output_tokens: int):
        user = self.user_collection.find_one({"_id": user_id})
        role = user.get("role", "Trial_User")  # Default to Trial_User if not set
        deduction_rate = config.role_deduction_rates.get(role, 1)  # Use the rates from config.py
        tokens_to_deduct = (n_input_tokens + n_output_tokens) * deduction_rate
        self.user_collection.update_one(
            {"_id": user_id},
            {"$inc": {"token_balance": -tokens_to_deduct}}
        )

    def get_user_role(self, user_id: int) -> str:
        """Determine the role of a user based on their user ID."""
        user = self.user_collection.find_one({"_id": user_id})
        if user and "role" in user:
            return user["role"]
        return "Trial_User"  # Default role if not explicitly set

    def get_user_count(self):
        return self.user_collection.count_documents({})

    def get_all_user_ids(self):
        # Fetch all documents from the user_collection, projecting only the '_id' field
        user_ids_cursor = self.user_collection.find({}, {"_id": 1})
        # Extract '_id' from each document and return them as a list
        return [user["_id"] for user in user_ids_cursor]

    
    def get_users_and_roles(self):
    # Fetch all users and project only the first_name and role
        users_cursor = self.user_collection.find({}, {"username": 1,"first_name": 1, "role": 1})
        return list(users_cursor)
    
    def find_users_by_role(self, role: str):
        return list(self.user_collection.find({"role": role}))

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

    def update_total_topup(self, user_id, amount):
        self.user_collection.update_one(
            {"_id": user_id},
            {"$inc": {"total_topup": amount}}
        )

    def update_total_donated(self, user_id, amount):
        self.user_collection.update_one(
            {"_id": user_id},
            {"$inc": {"total_donated": amount}}
        )


    def get_user_euro_balance(self, user_id: int) -> float:
    
        user = self.user_collection.find_one({"_id": user_id})
        return user.get("euro_balance", 0.0)

    def get_user_financials(self, user_id):
        user_data = self.user_collection.find_one({"_id": user_id}, {"total_topup": 1, "total_donated": 1})
        if not user_data:
            return {"total_topup": 0, "total_donated": 0}  # Defaults in case the fields are missing
        return {
            "total_topup": user_data.get("total_topup", 0),  # Return 0 if the field doesn't exist
            "total_donated": user_data.get("total_donated", 0)
        }


    def deduct_euro_balance(self, user_id: int, euro_amount: float):
        self.check_if_user_exists(user_id, raise_exception=True)
    # Ensure the deduction amount is not negative to avoid accidental balance increase
        if euro_amount < 0:
            raise ValueError("Deduction amount must be positive")
        self.user_collection.update_one(
            {"_id": user_id},
            {"$inc": {"euro_balance": -euro_amount, "total_spent": euro_amount}}
        )

    def deduct_cost_for_action(self, user_id: int, action_type: str, action_params: dict):
        user_role = self.get_user_role(user_id)
        deduction_rate = config.role_deduction_rates.get(user_role, 1)

        # Retrieve the pricing information from the `config.models` dictionary
        model_info = config.models["info"].get(action_type)
        if not model_info:
            raise ValueError(f"Unknown action type: {action_type}")

        # Initialize the cost variable
        cost_in_euros = 0

        # Handle text models (per 1000 tokens)
        if action_type in ['gpt-3.5-turbo', 'gpt-3.5-turbo-16k', 'gpt-4', 'gpt-4-1106-preview', 'gpt-4-vision-preview', 'text-davinci-003', 'gpt-4-turbo-2024-04-09']:

            # Retrieve the input/output pricing from `config.models`
            price_per_1000_input = model_info.get('price_per_1000_input_tokens', 0)
            price_per_1000_output = model_info.get('price_per_1000_output_tokens', 0)

            # Calculate the cost based on input and output tokens
            cost_in_euros = ((action_params.get('n_input_tokens', 0) / 1000) * price_per_1000_input + (action_params.get('n_output_tokens', 0) / 1000) * price_per_1000_output) * deduction_rate

        # Handle DALLE-2 (per image)
        elif action_type == 'dalle-2':
            n_images = action_params.get('n_images', 1)
            resolution = action_params.get('resolution', '1024x1024')

            # Retrieve the cost per image based on resolution
            dalle2_resolutions = model_info.get('resolutions', {})
            price_per_image = dalle2_resolutions.get(resolution, {}).get('price_per_1_image', 0.020)

            cost_in_euros = n_images * price_per_image * deduction_rate

            # Update DALL-E 2 tracking in the user database
            self.user_collection.update_one(
                {"_id": user_id},
                {"$inc": {"dalle_2.images": n_images, "dalle_2.cost": cost_in_euros}}
            )

        elif action_type == 'dalle-3':
            n_images = action_params.get('n_images', 1)
            quality = action_params.get('quality', 'standard')
            resolution = action_params.get('resolution', '1024x1024')

            # Retrieve pricing based on quality and resolution
            dalle3_qualities = model_info.get('qualities', {})
            quality_info = dalle3_qualities.get(quality, {})
            resolution_info = quality_info.get('resolutions', {}).get(resolution, {})
            price_per_image = resolution_info.get('price_per_1_image', 0.040)

            cost_in_euros = n_images * price_per_image * deduction_rate

            # Update DALL-E 3 tracking in the user database
            self.user_collection.update_one(
                {"_id": user_id},
                {"$inc": {"dalle_3.images": n_images, "dalle_3.cost": cost_in_euros}}
            )

        # Handle Whisper (per minute)
        elif action_type == 'whisper':
            audio_duration_minutes = action_params.get('audio_duration_minutes', 0)
            price_per_minute = model_info.get('price_per_1_min', 0.006)

            cost_in_euros = audio_duration_minutes * price_per_minute * deduction_rate

        else:
            raise ValueError(f"Unknown action type: {action_type}")

        # Deduct the calculated cost from the user's balance
        self.deduct_euro_balance(user_id, cost_in_euros)
        