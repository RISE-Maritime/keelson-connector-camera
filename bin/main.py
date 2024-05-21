import zenoh
from zenoh import QueryTarget
import logging
import warnings
import atexit
import json
import time
import keelson
from terminal_inputs import terminal_inputs
from keelson.payloads.CompressedImage_pb2 import CompressedImage
from keelson.payloads.RawImage_pb2 import RawImage
from vidgear.gears import CamGear
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
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s %(message)s", level=args.log_level
    )
    logging.captureWarnings(True)
    warnings.filterwarnings("once")

    ## Construct session
    logging.info("Opening Zenoh session...")
    conf = zenoh.Config()
    if args.connect is not None:
        conf.insert_json5(zenoh.config.CONNECT_KEY, json.dumps(args.connect))
    session = zenoh.open(conf)

    def _on_exit():
        session.close()

    atexit.register(_on_exit)
    logging.info(f"Zenoh session established: {session.info()}")

    #################################################
    # Setting up PUBLISHER

    # Camera panorama
    key_exp_pub_camera = keelson.construct_pub_sub_key(
        realm=args.realm,
        entity_id=args.entity_id,
        subject="compressed_image",  # Needs to be a supported subject
        source_id=args.source_id,
    )
    pub_camera = session.declare_publisher(
        key_exp_pub_camera,
        priority=zenoh.Priority.INTERACTIVE_HIGH(),
        congestion_control=zenoh.CongestionControl.DROP(),
    )
    logging.info(f"Created publisher: {key_exp_pub_camera}")



    logging.info("Converting to frames from source url: %s", args.camera)

    
    # Opening a VideoCapture object using the supplied url
    stream  = CamGear(source=args.camera).start() 

    try:
        
        while True:
            
            (grabbed, frame) = stream.read()
            ingress_timestamp = time.time_ns()

            if not grabbed:
                logging.error("No frames returned from the stream. Exiting!")
                break

            logging.info("Got new frame, at time: %d", ingress_timestamp)

            height, width, _ = frame.shape
            logging.debug("with height: %d, width: %d", height, width)


            logging.debug("Processing raw frame")

            height, width, _ = frame.shape
            data = frame.tobytes()

            width_step = len(data) // height
            logging.debug(
                "Frame total byte length: %d, widthstep: %d", len(data), width_step
            )

            # if args.send == "raw":
            #     logging.debug("Send RAW frame...")
            #     # Create payload for raw image
            #     payload = RawImage()
            #     payload.timestamp.FromNanoseconds(ingress_timestamp)
            #     if args.frame_id is not None:
            #         payload.frame_id = args.frame_id
            #     payload.width = width
            #     payload.height = height
            #     payload.encoding = "bgr8"  # Default in OpenCV
            #     payload.step = width_step
            #     payload.data = data

            #     serialized_payload = payload.SerializeToString()
            #     envelope = keelson.enclose(serialized_payload)
            #     raw_publisher.put(envelope)
            #     logging.debug(f"...published on {raw_key}")

            # supported_formats = ["jpeg", "webp", "png"]

            if args.send in supported_formats:
                logging.debug(f"SEND {args.send} frame...")
                _, compressed_img = cv2.imencode(  # pylint: disable=no-member
                    MCAP_TO_OPENCV_ENCODINGS[args.send], frame
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
                pub_camera.put(envelope)
                logging.debug(f"...published on {key_exp_pub_camera}")

            # if args.save == "raw":
            #     logging.debug("Saving raw frame...")
            #     filename = f'{ingress_timestamp}_"bgr8".raw'
            #     cv2.imwrite(filename, img)

            # if args.save in supported_formats:
            #     logging.debug(f"Saving {args.save} frame...")
            #     ingress_timestamp_seconds = ingress_timestamp / 1e9
            #     # Create a datetime object from the timestamp
            #     ingress_datetime = datetime.datetime.fromtimestamp(
            #         ingress_timestamp_seconds
            #     )
            #     # Convert the datetime object to an ISO format string
            #     ingress_iso = ingress_datetime.strftime("%Y-%m-%dT%H%M%S-%fZ%z")
            #     filename = f"./rec/{ingress_iso}_{args.source_id}.{args.save}"
            #     cv2.imwrite(filename, img)

            # Doing some calculations to see if we manage to keep up with the framerate
            now = time.time()
            processing_frame_rate = now - previous
            previous = now

    

    except KeyboardInterrupt:
        logging.info("Closing down on user request!")
        stream.stop()

        logging.debug("Done! Good bye :)")