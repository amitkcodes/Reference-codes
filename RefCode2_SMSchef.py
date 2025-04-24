import requests
#your API secret from smschef(tool-APIkey)
apiSecret = "c59a9a09acd020a020f906e33903901446462dec"
deviceId = "00000000-0000-0000-b537-d050d47dc40a"

phone = '+919520010920'
message = 'Hello! I am successfully create SMS sender program by open sorce'

message = {
    "secret": apiSecret,
    "mode": "devices",
    "device": deviceId,
    "sim": 1,
    "priority": 1,
    "phone": phone,
    "message": message
}

r = requests.post(url = "https://www.cloud.smschef.com/api/send/sms", params = message)
  
# do something with response object
result = r.json()
print(result)
