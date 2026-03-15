import qi, time
s = qi.Session()
s.connect('tcp://127.0.0.1:9559')
m = s.service('ALMotion')
v = s.service('ALVideoDevice')

# Use async for all calls to avoid blocking
m.wakeUp(_async=True)
m.setStiffnesses('HeadYaw', 1.0, _async=True)
m.setStiffnesses('HeadPitch', 1.0, _async=True)
time.sleep(20)

for sub in v.getSubscribers():
    v.unsubscribe(sub)
print('Init done')

while True:
    time.sleep(10)
    m.setStiffnesses('HeadYaw', 1.0, _async=True)
    m.setStiffnesses('HeadPitch', 1.0, _async=True)
    for sub in v.getSubscribers():
        v.unsubscribe(sub)
