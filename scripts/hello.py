#!/usr/bin/env python2
"""Say hello when a person is detected in front of the robot."""

import qi
import time

session = qi.Session()
session.connect('tcp://127.0.0.1:9559')

tts = session.service('ALTextToSpeech')
mem = session.service('ALMemory')
people = session.service('ALPeoplePerception')

# Ensure people perception is running
people.setMaximumDetectionRange(3.0)

last_hello = 0
COOLDOWN = 10  # seconds between hellos

print('Waiting for people (Ctrl+C to stop)...')

sub = mem.subscriber('PeoplePerception/JustArrived')

def on_person(person_id):
    global last_hello
    now = time.time()
    if now - last_hello < COOLDOWN:
        return
    last_hello = now
    print('Person %s detected, saying hello' % person_id)
    tts.say('Hello!')

sub.signal.connect(on_person)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print('\nStopped.')
