import json

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .models import Project


class TaskNotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.project_id = self.scope["url_route"]["kwargs"]["project_id"]
        project_exists = await sync_to_async(
            Project.objects.filter(pk=self.project_id).exists,
            thread_sensitive=True,
        )()
        if not project_exists:
            await self.close(code=4404)
            return

        self.group_name = f"project_{self.project_id}"
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name,
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
