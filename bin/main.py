import zenoh
import logging
import warnings
import json
import time
import datetime
import keelson
from terminal_inputs import terminal_inputs
from keelson.payloads.foxglove.CompressedImage_pb2 import CompressedImage
from keelson.payloads.foxglove.RawImage_pb2 import RawImage
import cv2
import numpy
from collections import deque
from threading import Thread, Event

session = None
args = None
pub_camera = None
supported_formats = ["jpeg", "webp", "png"]
MCAP_TO_OPENCV_ENCODINGS = {"jpeg": ".jpg", "webp": ".webp", "png": ".png"}

#####################################################
"""
# Camera Connector

"""
if __name__ == "__main__":
    # Input arguments and configurations
    args = terminal_inputs()

    # Setup logger
    logging.basicConfig(format="%(asctime)s %(levelname)s [%(lineno)d]: %(message)s", level=args.log_level)
    logging.captureWarnings(True)
    warnings.filterwarnings("once")
    zenoh.init_log_from_env_or("error")

    # Construct session
    logging.info("Opening Zenoh session...")
    conf = zenoh.Config()
    if args.connect is not None:
        conf.insert_json5(zenoh.config.CONNECT_KEY, json.dumps(args.connect))

    with zenoh.open(conf) as session:
        logging.info(f"Zenoh session started")

        #################################################
        # Setting up PUBLISHER

        # Camera COMPRESSED IMAGE
        keyexp_comp = keelson.construct_pubsub_key(
            base_path=args.realm,
            entity_id=args.entity_id,
            subject="image_compressed",  # Needs to be a supported subject
            source_id=args.source_id,
        )
        pub_camera_comp = session.declare_publisher(
            keyexp_comp,
            priority=zenoh.Priority.INTERACTIVE_HIGH,
            congestion_control=zenoh.CongestionControl.DROP,
        )
        logging.info(f"Created publisher: {keyexp_comp}")

        # Camera RAW IMAGE
        keyexp_raw = keelson.construct_pubsub_key(
            base_path=args.realm,
            entity_id=args.entity_id,
            subject="image_raw",
            source_id=args.source_id,
        )
        pub_camera_raw = session.declare_publisher(
            keyexp_raw,
            priority=zenoh.Priority.INTERACTIVE_HIGH,
            congestion_control=zenoh.CongestionControl.DROP,
        )
        logging.info(f"Created publisher: {keyexp_raw}")

        logging.info("Camera source: %s", args.camera_url)

        # Opening a VideoCapture object using the supplied url
        cap = cv2.VideoCapture(args.camera_url) 
        fps = cap.get(cv2.CAP_PROP_FPS)  
        logging.info("Native framerate of stream: %s", fps)
        buffer = deque(maxlen=1)
        close_down = Event()

        def _capturer():
            while cap.isOpened() and not close_down.is_set():
                ret, img = cap.read()
                ingress_timestamp = time.time_ns()

                if not ret:
                    logging.error("No frames returned from the stream. Exiting!")
                    return

                logging.info("Got new frame, at time: %d", ingress_timestamp)

                height, width, _ = img.shape
                logging.debug("with height: %d, width: %d", height, width)

                buffer.append((ingress_timestamp, img))

        # Start capture thread
        t = Thread(target=_capturer)
        t.daemon = True
        t.start()

        try:
            previous = time.time()
            while True:
                try:
                    ingress_timestamp, img = buffer.pop()
                except IndexError:
                    time.sleep(0.01)
                    continue

                logging.debug("Processing raw frame")

                height, width, _ = img.shape
                data = img.tobytes()

                width_step = len(data) // height
                logging.debug(
                    "Frame total byte length: %d, widthstep: %d", len(
                        data), width_step
                )

                if args.send == "raw":
                    logging.debug("Send RAW frame...")
                    # Create payload for raw image
                    payload = RawImage()
                    payload.timestamp.FromNanoseconds(ingress_timestamp)
                    if args.frame_id is not None:
                        payload.frame_id = args.frame_id
                    payload.width = width
                    payload.height = height
                    payload.encoding = "bgr8"  # Default in OpenCV
                    payload.step = width_step
                    payload.data = data

                    serialized_payload = payload.SerializeToString()
                    envelope = keelson.enclose(serialized_payload)
                    pub_camera_raw.put(envelope)
                    logging.debug(f"...published on {keyexp_raw}")


                if args.send in supported_formats:
                    logging.debug(f"SEND {args.send} frame...")
                    _, compressed_img = cv2.imencode(  # pylint: disable=no-member
                        MCAP_TO_OPENCV_ENCODINGS[args.send], img
                    )
                    compressed_img = numpy.asarray(compressed_img)
                    data = compressed_img.tobytes()

                    payload = CompressedImage()
                    if args.frame_id is not None:
                        payload.frame_id = args.frame_id
                    payload.data = data
                    payload.format = args.send

                    serialized_payload = payload.SerializeToString()
                    envelope = keelson.enclose(serialized_payload)
                    pub_camera_comp.put(envelope)
                    logging.debug(f"...published on {keyexp_comp}")

                if args.save == "raw":
                    logging.debug("Saving raw frame...")
                    filename = f'{ingress_timestamp}_"bgr8".raw'
                    cv2.imwrite(filename, img)

                if args.save in supported_formats:
                    logging.debug(f"Saving {args.save} frame...")
                    ingress_timestamp_seconds = ingress_timestamp / 1e9
                    # Create a datetime object from the timestamp
                    ingress_datetime = datetime.datetime.fromtimestamp(
                        ingress_timestamp_seconds
                    )
                    # Convert the datetime object to an ISO format string
                    ingress_iso = ingress_datetime.strftime(
                        "%Y-%m-%dT%H%M%S-%fZ%z")
                    filename = f"{args.save_path}/{ingress_iso}_{args.source_id}.{args.save}"
                    cv2.imwrite(filename, img)

                # Doing some calculations to see if we manage to keep up with the framerate
                now = time.time()
                processing_frame_rate = now - previous
                previous = now

                logging.info(
                    "Processing framerate: %.2f (%d%% of native)",
                    processing_frame_rate,
                    100 * (processing_frame_rate / fps),
                )

        except KeyboardInterrupt:
            logging.info("Closing down on user request!")

            logging.debug("Joining capturer thread...")
            close_down.set()
            t.join()
            
            logging.debug(f"Done! Good bye :)")

    