# Mobile Strategy

## Muc tieu 3 giai doan

1. Giai doan 1 - API backend trung tam
- Mobile gui keypoints len backend.
- Backend tinh readiness + DTW.
- Uu diem: nhanh ra san pham, de dong bo scoring.

2. Giai doan 2 - Hybrid
- Mobile tinh readiness co ban on-device de feedback nhanh.
- Backend van tinh score chinh thuc.

3. Giai doan 3 - Edge/offline
- Dua mot phan motion_core on-device.
- Dong bo ket qua khi co mang.

## Khuyen nghi cong nghe

- Client mobile: Flutter (mot codebase iOS/Android).
- Pose on-device: MediaPipe Tasks.
- Networking: retry + timeout + idempotency key.
- Local store: SQLite de luu session tam khi offline.

## Cac API can bo sung tiep

- POST /v1/session/start
- POST /v1/session/{id}/frames
- POST /v1/session/{id}/score
- GET /v1/session/{id}/feedback

## Quay truc tiep student voi nhieu bai tap lien tiep

De xuat luong on dinh cho live class:

1. Client tai giao an buoi tap (exercise plan):
- [{name: squat, mode: reps, target_reps: 12}, {name: plank, mode: hold, target_seconds: 45}, ...]

2. Bat dau session:
- Goi POST /v1/live/session/start voi danh sach bai.

3. Moi frame camera:
- MediaPipe Pose trich keypoints 1 nguoi.
- Tinh signal [0..1] theo do tuong dong phase voi teacher.
- Goi POST /v1/live/session/frame.

4. Hien thi realtime:
- Neu mode reps: hien thi rep_count/target.
- Neu mode hold: hien thi hold_seconds/target.
- Khi completed: auto chuyen bai tiep theo + countdown 3 giay.

4b. Checkpoint xac nhan thu cong:
- Sau moi quang nghi hoac het bai, dung dem va doi nguoi dung bam xac nhan.
- Sau xac nhan moi cho readiness gate chay lai truoc khi dem tiep.
- Cach nay giam nhu cau phan loai bai tap online khi student doi bai.

5. Ket thuc buoi:
- Tong hop ket qua tung bai + frame quality + readiness trung binh.

Luu y quan trong:
- De tranh nham bai khi student di chuyen, gate readiness phai dat truoc khi bat dau dem.
- Neu signal dao dong manh, ap dung smoothing 300-500 ms truoc khi feed tracker.

## Doc thong bao bang loa (TTS)

- Server-side (hien tai): pyttsx3, khong can internet.
- Client-side (khuyen nghi cho mobile):
	- Android: TextToSpeech API
	- iOS: AVSpeechSynthesizer
- Nen gom thong bao theo muc uu tien de tranh doc chong cheo:
	1. Bao an toan/pose sai
	2. Bat dau-ket thuc set, chuyen bai
	3. Dem rep

## Chi so chat luong

- p95 readiness latency < 120 ms
- p95 align latency < 600 ms (chuoi 8-12s)
- Ty le frame hop le > 95%
