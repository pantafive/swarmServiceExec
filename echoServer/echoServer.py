#! /usr/bin/python3
import os
from aiohttp import web

try:
    MY_NAME = os.environ['SERVICE_NAME'].capitalize()
except KeyError:
    MY_NAME = 'NoName'


async def say_hello(request):
    response = {'greeting': f"Hello, I'am {MY_NAME}."}
    return web.json_response(response)

app = web.Application()
app.add_routes([web.get('/', say_hello)])
web.run_app(app, port=8080)
