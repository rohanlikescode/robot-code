#!/usr/bin/env python3

# `None` for dev_num makes the camera fill in automatically
CONFIG = {
    "cameras": [
        {
            "name": "front",
            "dev_num": None,
            "ip": "10.1.14.5",
            "port": "5808"
        },
        {
            "name": "back",
            "dev_num": None,
            "ip": "10.1.14.5",
            "port": "5809"
        },
    ],
    "check_interval": 0.1,
    "do_config_cameras": False
}

from time import sleep
import subprocess
from pathlib import Path
from sys import stdout
import traceback

def run_cap(ar, *args):
    return subprocess.run(ar, *args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

class Camera:
    def __init__(self, dev_num, ip, port, usb_info):
        self.dev_num = dev_num
        self.usb_info = usb_info
        self.ip = ip
        self.port = port
        self.process = None
        self.stdout_w = None
        self.stdout_r = None

    @staticmethod
    def dev_num_exists(dev_num):
        path = Path("/dev/video{}".format(dev_num))
        return path.exists()

    def exists(self):
        return self.dev_num_exists(self.dev_num)

    @staticmethod
    def get_usb_info(dev_num):
        KEY = "ID_PATH_TAG"
        cmd = "udevadm info --query=property /dev/video{}".format(dev_num).split(' ')
        p1 = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        p2 = subprocess.Popen(["grep", KEY], stdin=p1.stdout, stdout=subprocess.PIPE)
        p1.stdout.close()  # Allow p1 to receive a SIGPIPE if p2 exits.
        out = p2.communicate()
        return out[0] # grab stdout

    def resolve_usb_info(self):
        self.usb_info = self.get_usb_info(self.dev_num)

    def cfg_v4l2(self):
        cmd = "v4l2-ctl -d /dev/video{} -c exposure_auto=1 -c exposure_absolute=300".format(self.dev_num)
        cmd = cmd.split(' ')
        subprocess.run(cmd, check=True)

    def spawn_process(self):
        print("Starting process for camera", self)
        if self.usb_info is None:
            raise ValueError("usb_info not set!")
        if self.stdout_r is None or self.stdout_w is None:
            self.stdout_w = open(self.usb_info, 'w+b')
            self.stdout_r = open(self.usb_info, 'rt', buffering=1)
        self.process = subprocess.Popen([
            'gst-launch-1.0',
            '-v', 'v4l2src',
            'device=/dev/video{}'.format(self.dev_num),
            '!',
            'video/x-raw,width=320,height=240,framerate=30/1',
            '!',
            'x264enc', 'speed-preset=1', 'tune=zerolatency', 'bitrate=512',
            '!',
            'rtph264pay'
            '!',
            'udpsink', 'host={}'.format(self.ip), 'port={}'.format(self.port)
        ], stdout=self.stdout_w, stderr=self.stdout_w)

    def end_process(self):
        print("Ending process for camera", self)
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            print("Process running 1 second after SIGTERM, escalating to SIGKILL")
            self.process.kill()

    def __str__(self):
        return "Camera({}, {})".format(self.dev_num, self.usb_info)

def list_dev_nums():
    candidates = []
    for cand in (p.name[5:] for p in Path("/dev/").glob("video*")):
        try:
            dev_num = int(cand)
            if Camera.dev_num_exists(dev_num):
                candidates.append(dev_num)
        except ValueError:
            pass
    return candidates

# Not robust to unplugs during call
def make_cam_list(cfg):
    cameras = []
    candidates = list_dev_nums()
    # Sort None dev_nums last, they'll fill in
    for camera in sorted(cfg["cameras"], key=lambda c: (c["dev_num"] is None, c["dev_num"])):
        filtered_dev_num = camera["dev_num"]
        if filtered_dev_num is None:
            print("Encountered null dev_num in config for camera `", camera["name"], "`, attempting to assign from remaining devices")
            if len(candidates) > 0:
                filtered_dev_num = candidates[0]
            else:
                print("ERROR: device candidate list exhausted! Camera will not be instantiated!")
                continue
        c = Camera(filtered_dev_num, camera["ip"], camera["port"], None)
        if not c.exists():
            print("ERROR: Resolved camera `", camera["name"], "` does not exist on dev", filtered_dev_num , "! It will not be instantiated!")
            continue
        c.resolve_usb_info()
        print("Config", camera["name"], "successfully mapped to", c)
        cameras.append(c)
        candidates.remove(c.dev_num)
    return cameras


def main(cfg):
    print("======= Grabbing Cameras =======")
    cameras = make_cam_list(cfg)
    print("===== Initializing Cameras =====")
    for cam in cameras:
        if cfg["do_config_cameras"]:
            cam.cfg_v4l2()
        cam.spawn_process()
    while True:
        for cam in cameras:
            try:
                # Flush IO
                for l in cam.stdout_r.readlines():
                    print("STDOUTERR", cam, ':', l, end='')
                # Health checks
                if not cam.exists():
                    print(cam, "no longer exists, searching for candidate...")
                    # Assume camera was unplugged, find another camera with the proper USB info
                    candidates = list_dev_nums()
                    print("Examining candidates on /dev/video + ", candidates)
                    for cand_num in candidates:
                        usb_info = Camera.get_usb_info(cand_num)
                        if usb_info == cam.usb_info:
                            print("Found matching candidate on /dev/video{}".format(cand_num))
                            cam.end_process()
                            cam.dev_num = cand_num
                            if cfg["do_config_cameras"]:
                                cam.cfg_v4l2()
                            cam.spawn_process()
                            break
                elif cam.process.poll() is not None:
                    # finish printing stdout, rebuild
                    print(cam, "process spuriously finished, attempting restart...")
                    cam.spawn_process()
            except: # bad practice but we don't want to stop the process
                print("Exception occurred while handling", cam, ":")
                traceback.print_exc()
        stdout.flush() # required for non-interactive stdout, such as tee-ing to a log file
        sleep(cfg["check_interval"])


if __name__ == "__main__":
    main(CONFIG)
