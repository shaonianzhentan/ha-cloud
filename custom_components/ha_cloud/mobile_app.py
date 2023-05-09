from homeassistant.helpers.network import get_url
import aiohttp, json

class MobileApp():

    def __init__(self, hass):        
        self.hass = hass

    async def async_http_post(self, url, data):
        headers = {
            'Content-Type': 'application/json'
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=json.dumps(data), headers=headers) as response:
                return await response.json()

    def get_webhook_url(self, webhook_id):
        ''' 获取WebHook地址 '''
        base_url = get_url(self.hass)
        return f"{base_url}/api/webhook/{webhook_id}"

    async def async_update_registration(self, webhook_id, data):
        ''' 更新设备 '''
        webhook_url = self.get_webhook_url(webhook_id)
        return await self.async_http_post(webhook_url, {
            "data": data,
            "type": "update_registration"
        })

    async def async_update_sensor_states(self, webhook_id, sensor_data):
        webhook_url = self.get_webhook_url(webhook_id)
        
        unique_id = sensor_data.get('unique_id')

        result = await self.async_http_post(webhook_url, {
            "data": [ sensor_data ],
            "type": "update_sensor_states"
        })
        bl = result.get(unique_id)
        if bl is not None and 'error' in bl:
            error = bl.get('error')
            if error.get('code') == 'not_registered':
                await self.async_http_post(webhook_url, {
                    "data": sensor_data,
                    "type": "register_sensor"
                })