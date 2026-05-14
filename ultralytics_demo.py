from ultralytics import YOLO
from PIL import Image
from huggingface_hub import hf_hub_download
from pathlib import Path
import os

REPO_ID = "Salesforce/GPA-GUI-Detector"
FILENAME = "model.pt"
LOCAL_DIR = "./models"

# Load the model

hf_hub_download(REPO_ID, FILENAME, local_dir=LOCAL_DIR)
model = YOLO(Path(LOCAL_DIR) / FILENAME)

# Run inference with custom confidence and image size
results = model.predict(
    source="images/screenshot_booking.png",
    conf=0.05,        # confidence threshold
    imgsz=640,        # input image size
    iou=0.7,          # NMS IoU threshold
)

# Parse results
boxes = results[0].boxes.xyxy.cpu().numpy()   # bounding boxes in [x1, y1, x2, y2]
scores = results[0].boxes.conf.cpu().numpy()  # confidence scores

# Draw results on image
img = Image.open("images/screenshot_booking.png")
for box, score in zip(boxes, scores):
    x1, y1, x2, y2 = box
    print(f"Detected UI element at [{x1:.0f}, {y1:.0f}, {x2:.0f}, {y2:.0f}] (conf: {score:.2f})")

# Or save the annotated image directly
results[0].save("images/result_booking.png")
