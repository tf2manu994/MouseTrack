from __future__ import division
from multiprocessing import Process, Queue
import time

from core._os import get_resolution, get_mouse_click, get_key_press, KEYS, MOUSE_BUTTONS
from core.messages import *
from core.functions import RefreshRateLimiter
from core.constants import *
from track import background_process

CONFIG.save()
mouse_inactive_delay = 2

updates_per_second = CONFIG.data['Main']['UpdatesPerSecond']
timer = {'UpdateScreen': CONFIG.data['Frequency']['CheckScreen'],
         'UpdatePrograms': CONFIG.data['Frequency']['CheckPrograms'],
         'Save': CONFIG.data['Frequency']['Save'],
         'ReloadProgramList': CONFIG.data['Frequency']['ReloadPrograms']}


timer = {k: v * updates_per_second for k, v in timer.iteritems()}

if __name__ == '__main__':

    store = {'Resolution': {'Current': get_resolution(),
                            'Previous': None},
             'Mouse': {'Position': {'Current': None,
                                    'Previous': None},
                       'NotMoved': 0,
                       'Inactive': False,
                       'Clicked': False,
                       'OffScreen': False},
             'Keyboard': {'KeysPressed': {k: False for k in KEYS.keys()}},
             'LastActivity': 0,
             'LastSent': 0}
    mouse_pos = store['Mouse']['Position']

    #Start threaded process
    q_send = Queue()
    q_recv = Queue()
    p = Process(target=background_process, args=(q_send, q_recv))
    p.daemon = True
    p.start()
    i = 0
    notify.queue(START_MAIN)
    while True:
        with RefreshRateLimiter(updates_per_second) as limiter:
            
            #Send data to thread
            try:
                if frame_data:
                    last_sent = i - store['LastSent']
                    if last_sent:
                        frame_data['Ticks'] = last_sent
                    q_send.put(frame_data)
                    store['LastSent'] = i
            except NameError:
                pass
                
            #Print any messages from previous loop
            notify_extra = ''
            received_data = []
            while not q_recv.empty():
                received_data.append(q_recv.get())
            if received_data:
                notify_extra = ' | '.join(received_data)
            notify_output = notify.output()
            if notify_extra:
                if notify_output:
                    notify_output = notify_extra + ' | ' + notify_output
                else:
                    notify_output = notify_extra
            if notify_output:
                print notify_output

            frame_data = {}
            mouse_pos['Current'] = limiter.mouse_pos()

            #Check if mouse is inactive (such as in a screensaver)
            if mouse_pos['Current'] is None:
                if not store['Mouse']['Inactive']:
                    notify.queue(MOUSE_UNDETECTED)
                    store['Mouse']['Inactive'] = True
                time.sleep(mouse_inactive_delay)
                continue

            #Check if mouse left the monitor
            elif (not 0 <= mouse_pos['Current'][0] < store['Resolution']['Current'][0]
                  or not 0 <= mouse_pos['Current'][1] < store['Resolution']['Current'][1]):
                if not store['Mouse']['OffScreen']:
                    notify.queue(MOUSE_OFFSCREEN)
                    store['Mouse']['OffScreen'] = True
            elif store['Mouse']['OffScreen']:
                notify.queue(MOUSE_ONSCREEN)
                store['Mouse']['OffScreen'] = False

            #Notify if mouse is no longer inactive
            if store['Mouse']['Inactive']:
                store['Mouse']['Inactive'] = False
                notify.queue(MOUSE_DETECTED)

            #Check if mouse is in a duplicate position
            if mouse_pos['Current'] is None or mouse_pos['Current'] == mouse_pos['Previous']:
                store['Mouse']['NotMoved'] += 1
            elif store['Mouse']['NotMoved']:
                store['Mouse']['NotMoved'] = 0
            if not store['Mouse']['NotMoved']:
                if not store['Mouse']['OffScreen']:
                    frame_data['MouseMove'] = (mouse_pos['Previous'], mouse_pos['Current'])
                    notify.queue(MOUSE_POSITION, mouse_pos['Current'])
                    store['LastActivity'] = i

            #Mouse clicks
            mouse_click = get_mouse_click()
            if mouse_click:
                if not store['Mouse']['Clicked']:
                    if not store['Mouse']['OffScreen']:
                        notify.queue(MOUSE_CLICKED, mouse_pos['Current'])
                        frame_data['MouseClick'] = mouse_pos['Current']
                        store['LastActivity'] = i
                    else:
                        notify.queue(MOUSE_CLICKED_OFFSCREEN)
                    store['Mouse']['Clicked'] = limiter.time
                elif store['Mouse']['Clicked'] > 0 and store['Mouse']['Clicked'] + 1 < limiter.time:
                    store['Mouse']['Clicked'] *= -1
                    notify.queue(MOUSE_HELD)
            else:
                if store['Mouse']['Clicked'] < 0 and store['Mouse']['Clicked'] > 1 - limiter.time:
                    notify.queue(MOUSE_UNCLICKED)
                store['Mouse']['Clicked'] = False

            #Key presses
            keys_pressed = []
            for k in KEYS:
                if get_key_press(KEYS[k]):
                    if store['Keyboard']['KeysPressed'][k]:
                        pass
                    else:
                        keys_pressed.append(k)
                        store['Keyboard']['KeysPressed'][k] = True
                elif store['Keyboard']['KeysPressed'][k]:
                    store['Keyboard']['KeysPressed'][k] = False
            if keys_pressed:
                frame_data['Keys'] = keys_pressed
                notify.queue(KEYBOARD_PRESSES, keys_pressed)
                store['LastActivity'] = i

            #Check if resolution has changed
            if not i % timer['UpdateScreen']:
                store['Resolution']['Current'] = get_resolution()
                if store['Resolution']['Previous'] != store['Resolution']['Current']:
                    if store['Resolution']['Previous'] is not None:
                        notify.queue(RESOLUTION_CHANGED, store['Resolution']['Previous'],
                                                         store['Resolution']['Current'])
                    frame_data['Resolution'] = store['Resolution']['Current']
                    store['Resolution']['Previous'] = store['Resolution']['Current']

            #Send request to update programs
            if not i % timer['UpdatePrograms']:
                frame_data['Programs'] = False
                
            #Send request to reload program list
            if not i % timer['ReloadProgramList']:
                frame_data['Programs'] = True

            #Send save request
            if i and not i % timer['Save']:
                if store['LastActivity'] > i - timer['Save']:
                    frame_data['Save'] = True
                    notify.queue(SAVE_START)
                else:
                    notify.queue(SAVE_SKIP, (i - store['LastActivity']) // updates_per_second)
            
            mouse_pos['Previous'] = mouse_pos['Current']
            i += 1
