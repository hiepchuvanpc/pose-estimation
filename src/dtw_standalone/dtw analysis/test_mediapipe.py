import cv2
import time
import argparse
from core.pose_tracker import PoseTracker
from utils.visualizer import Visualizer

def test_video(video_path, model_path):
    print(f"Testing video: {video_path} using model: {model_path}")
    tracker = PoseTracker(model_asset_path=model_path)
    visualizer = Visualizer()
    
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0: fps = 30
    
    frame_idx = 0
    start_time = time.time()
    
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
            
        timestamp_ms = int(frame_idx * 1000 / fps)
        landmarks, results = tracker.process_frame(frame, timestamp_ms)
        
        # Vẽ landmarks
        annotated_frame = visualizer.draw_landmarks(frame.copy(), results)
        
        # Overlay thông tin
        cv2.putText(annotated_frame, f"Frame: {frame_idx}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        if landmarks is not None:
            cv2.putText(annotated_frame, "Status: Detected", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        else:
            cv2.putText(annotated_frame, "Status: Not Detected", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            
        cv2.imshow("MediaPipe Test", annotated_frame)
        
        # Bấm 'q' để thoát
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
        frame_idx += 1
        
    end_time = time.time()
    print(f"Processed {frame_idx} frames in {end_time - start_time:.2f} seconds.")
    print(f"Average processing speed: {frame_idx / (end_time - start_time):.2f} FPS")
    
    cap.release()
    cv2.destroyAllWindows()
    tracker.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=str, required=True, help="Path to the video file")
    parser.add_argument("--model", type=str, default="pose_landmarker_lite.task", help="Path to the .task model file")
    args = parser.parse_args()
    
    test_video(args.video, args.model)
