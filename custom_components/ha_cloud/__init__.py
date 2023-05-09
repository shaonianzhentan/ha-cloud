from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CoreState, HomeAssistant, Context
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.network import get_url
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_STATE_CHANGED,
)
import paho.mqtt.client as mqtt
import logging, json, time, uuid, aiohttp, urllib

from .mobile_app import MobileApp
from .EncryptHelper import EncryptHelper
from .manifest import manifest

_LOGGER = logging.getLogger(__name__)
DOMAIN = manifest.domain

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    print(entry.entry_id)
    config = entry.data
    topic = entry.entry_id
    token = config['token']
    hass.data[DOMAIN] = await hass.async_add_executor_job(HaMqtt, hass, {
        'topic': topic,
        'token': token
    })

    async def qrcode_service(service):
        qrc = urllib.parse.quote(f'ha:{token}#{topic}')

        title = '使用【HomeAssistant家庭助理】小程序扫码关联'
        message = f'[![qrcode](https://cdn.dotmaui.com/qrc/?t={qrc})](https://github.com/shaonianzhentan/ha_mqtt) <font size="5">内含密钥和订阅主题<br/>请勿截图分享</font>'
        await hass.services.async_call('persistent_notification', 'create', { 'title': title, 'message': message })

    hass.services.async_register(DOMAIN, 'qrcode', qrcode_service)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data[DOMAIN].unload()
    del hass.data[DOMAIN]
    return True

class HaMqtt():

    def __init__(self, hass, config):
        self.hass = hass
        self.topic = config.get('topic')
        self.token = config.get('token')
        self.msg_cache = {}
        self.is_connected = False
        self.mobile_app = MobileApp(hass)

        if hass.state == CoreState.running:
            self.connect()
        else:
            hass.bus.listen_once(EVENT_HOMEASSISTANT_STARTED, self.connect)

    @property
    def encryptor(self):
        return EncryptHelper(self.token, time.strftime('%Y-%m-%d', time.localtime()))

    def connect(self, event=None):
        HOST = 'test.mosquitto.org'
        PORT = 1883
        client = mqtt.Client()        
        self.client = client
        client.on_connect = self.on_connect
        client.on_message = self.on_message
        client.on_subscribe = self.on_subscribe
        client.on_disconnect = self.on_disconnect
        client.connect(HOST, PORT, 60)
        client.loop_start()

    def on_connect(self, client, userdata, flags, rc):
        self.client.subscribe(self.topic, 2)
        self.is_connected = True

    def unload(self):
        self.client.disconnect()

    # 清理缓存消息
    def clear_cache_msg(self):
        now = int(time.time())
        for key in list(self.msg_cache.keys()):
            # 缓存消息超过10秒
            if key in self.msg_cache and now - 10 > self.msg_cache[key]:
                del self.msg_cache[key]

    def on_message(self, client, userdata, msg):
        payload = str(msg.payload.decode('utf-8'))
        try:
            # 解析消息
            data = json.loads(self.encryptor.Decrypt(payload))
            _LOGGER.debug(data)
            self.clear_cache_msg()

            now = int(time.time())
            # 判断消息是否过期(5s)
            if now - 5 > data['time']:
                print('【ha-mqtt】消息已过期')
                return

            msg_id = data['id']
            # 判断消息是否已接收
            if msg_id in self.msg_cache:
                print('【ha-mqtt】消息已处理')
                return

            # 设置消息为已接收
            self.msg_cache[msg_id] = now

            # 消息处理
            self.hass.loop.create_task(self.async_handle_message(data))

        except Exception as ex:
            print(ex)

    def on_subscribe(self, client, userdata, mid, granted_qos):
        print("【ha_mqtt】On Subscribed: qos = %d" % granted_qos)

    def on_disconnect(self, client, userdata, rc):
        print("【ha_mqtt】Unexpected disconnection %s" % rc)
        self.is_connected = False

    def publish(self, topic, data):
        # 判断当前连接状态
        if self.client._state == 2:
            _LOGGER.debug('断开重连')
            self.client.reconnect()
            self.client.loop_start()

        # 加密消息
        payload = self.encryptor.Encrypt(json.dumps(data))
        self.client.publish(topic, payload, qos=1)

    async def async_handle_message(self, data):
        msg_id = data['id']
        msg_topic = data['topic']
        msg_type = data['type']
        msg_data = data['data']
        
        body = msg_data.get('data', {})
        print(data)
        result = None

        if msg_type == 'registrations': # 注册
            base_url = get_url(self.hass).strip('/')
            result = await self.async_http_post(f"{base_url}/mobile_app/registrations", body)
        elif msg_type == 'mobile_app': # 移动设备
            url = self.mobile_app.get_webhook_url(msg_data['webhook_id'])
            result = await self.async_http_post(url, body)
        elif msg_type == 'rest': # REST API
            base_url = get_url(self.hass).strip('/')
            method = msg_data['method'].lower()
            url = base_url + msg_data['path']
            if method == 'get':
                result = await self.async_http_get(url, body)
            elif method == 'post':
                result = await self.async_http_post(url, body)

        if result is not None:
            self.publish(msg_topic, {
                'id': msg_id,
                'time': int(time.time()),
                'type': msg_type,
                'data': result
            })

    async def async_http_post(self, url, data):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "content-type": "application/json",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=json.dumps(data), headers=headers) as response:
                return await response.json()

    async def async_http_get(self, url, data):
        headers = {
            "Authorization": f"Bearer {self.token}",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=data, headers=headers) as response:
                return await response.json()