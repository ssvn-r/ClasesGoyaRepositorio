import json

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser

from .services import MembershipService


class TaskNotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.project_id = self.scope["url_route"]["kwargs"]["project_id"]
        self.group_name = f"project_{self.project_id}"
        self.user = self.scope.get("user", AnonymousUser())

        if not self.user.is_authenticated:
            await self.close(code=4401)
            return
        is_member = await database_sync_to_async(
            MembershipService.is_member
        )(self.user, self.project_id)
        if not is_member:
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )
        await self.accept()
        self.joined = True
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "presence_update",
                "payload": {
                    "user": self.user.username,
                    "status": "online",
                },
            },
        )

    async def disconnect(self, close_code):
        if getattr(self, "joined", False):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name,
            )
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "presence_update",
                    "payload": {
                        "user": self.user.username,
                        "status": "offline",
                    },
                },
            )

    async def receive(self, text_data):
        data = json.loads(text_data)
        await self.send(
            text_data=json.dumps({"echo": data}),
        )

    async def task_notification(self, event):
        await self.send(
            text_data=json.dumps(event["payload"]),
        )

    async def presence_update(self, event):
        await self.send(
            text_data=json.dumps(event["payload"]),
        )
