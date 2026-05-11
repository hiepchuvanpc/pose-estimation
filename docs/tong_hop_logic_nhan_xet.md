# Tong hop toan bo logic nhan xet (post-workout feedback)

Tai lieu nay trich va gom cac logic nhan xet hien dang duoc dung trong backend/frontend.

Nguon chinh:
- `app/src/motion_api/main.py`
- `app/web/static/js/main.js`

## 1) Luong xu ly tong quan

Trong `_analyze_segment(...)` backend:
1. Trich pose student tu video.
2. Chay canh tranh 2 huong canh:
- `normal`
- `mirror` (lat trai/phai)
3. Chon huong co `normalized_distance` tot hon.
4. Tao `valid_path` DTW, lay `sample_path` de phan tich.
5. Tinh:
- `issues` (feature-level)
- `joint_analyses` (khop-level)
- `frame_analyses`
- `rep_feedback` (cau nhan xet theo rep/set)
- `scoring` (diem ky thuat)
6. Tra output cho UI, gom `reference_plane`, `action_items`, `rep_feedback`.

Ref: `main.py` dong ~3728-3854.

## 2) Nhom loi tong quan (feature-group feedback)

### 2.1 Tinh muc lech theo nhom feature
Ham: `_group_issue_scores(...)`
- Duyet tung nhom trong `FEATURE_GROUPS`.
- Tren moi cap frame DTW `(ti, si)`, lay sai khac tuyet doi tren cac chieu feature cua nhom.
- Score nhom = trung binh sai khac.
- Sap xep giam dan theo do lech.

Ref: `main.py` dong ~1068-1089.

### 2.2 Chuyen thanh cau feedback tong quan
Ham: `_issue_feedback(...)`
- Chi lay top 3 nhom loi.
- Bo qua neu `score < 0.1`.
- Muc do:
- `>= 0.26`: "lech nhieu"
- `>= 0.17`: "lech vua"
- con lai: "lech nhe"
- Neu nhan co chu "tay": dung mau cau cho truc vai-khuyu-co tay.
- Nhom khac: mau cau cho bien do/quy dao.
- Neu khong co loi dang ke: cau mac dinh "Dong tac gan voi video mau...".

Ref: `main.py` dong ~1092-1112.

## 3) Phan tich khop chi tiet (joint-level)

### 3.1 Tinh huong lech vi tri
Ham: `_direction_labels(dx, dy, dz)`
Nguong:
- `dx <= -0.045` -> `lech trai`
- `dx >= 0.045` -> `lech phai`
- `dy <= -0.045` -> `cao hon`
- `dy >= 0.045` -> `thap hon`
- `dz <= -0.09` -> `ra truoc hon`
- `dz >= 0.09` -> `ra sau hon`
- Neu khong vuot nguong -> `gan dung vi tri mau`

Ref: `main.py` dong ~1463-1477.

### 3.2 Tong hop theo khop
Ham: `_joint_analysis(...)`
- Tren tung khop trong `JOINT_ANALYSIS_SPECS`, tinh:
- `angle_delta_deg` trung binh
- `position_delta` (x,y,z) trung binh
- `direction` tu `_direction_labels`
- `vertical_axis_delta_deg` gom tu cac frame (trung binh)
- Sap xep theo `magnitude_deg` giam dan.

Ref: `main.py` dong ~1540+.

### 3.3 Loi khop theo tung frame
Ham: `_frame_joint_errors(...)`
- Tinh `angle_delta_deg`, `magnitude_deg`, `direction` cho moi khop.
- Danh dau `highlight` khi `abs(angle_delta) >= 12.0`.

Ref: `main.py` dong ~1996-2018.

## 4) Sinh cau huong dan sua (coaching text)

### 4.1 Muc do lech theo goc
Ham: `_severity_label(...)`
- `>= 30`: `cao`
- `>= 18`: `vua`
- `>= 10`: `nhe`
- con lai: `nho`

Ref: `main.py` dong ~1115-1123.

### 4.2 Gan pha trong rep
Ham: `_phase_hint_from_frame(...)`
Theo ti le vi tri trong chu ky rep:
- `< 0.2`: `dau rep`
- `< 0.48`: `pha xuong`
- `< 0.62`: `day rep`
- `< 0.88`: `pha len`
- con lai: `cuoi rep`

Ref: `main.py` dong ~1126-1138.

### 4.3 Pattern hint theo loai khop
Ham: `_joint_pattern_hint(...)`
- knee -> huong dan giu goi
- hip -> huong dan xiet core/giu hong can
- shoulder -> mo nguc/ha vai
- elbow -> giu khuyu on dinh
- default -> giu dung truc chuyen dong

Ref: `main.py` dong ~1141-1151.

### 4.4 Chuyen huong lech thanh lenh sua
Ham: `_direction_correction(...)`
Map:
- `lech trai` -> `dua ... sang phai`
- `lech phai` -> `dua ... sang trai`
- `cao hon` -> `ha ... xuong`
- `thap hon` -> `nang ... len`
- `ra truoc hon` -> `dua ... lui lai mot chut`
- `ra sau hon` -> `dua ... ra truoc mot chut`

Co che:
- loai trung
- gioi han toi da 2 hanh dong cu the

Ref: `main.py` dong ~1154-1177.

### 4.5 Tao feedback theo rep/set
Ham: `_rep_feedback_entries(...)`
- Mode khong phai `reps`:
- Lay toi da 6 loi nang nhat (`magnitude >= 10`).
- Tao `coaching_cues` + `text`.
- Mode `reps`:
- Gom loi theo tung rep, moi khop giu frame xau nhat.
- Moi rep lay top 6, bo qua loi `< 10`.
- Tao cau theo mau: rep + pha + do lech + cach sua.
- Ket qua tra ve:
- `details`
- `coaching_cues`
- `text`

Ref: `main.py` dong ~2021-2105.

## 5) Diem ky thuat (scoring)

Ham: `_build_segment_scoring(...)`

### 5.1 Thanh phan diem
- `similarity_score = clamp(similarity * 100)`
- `tempo_score = clamp(100 - normalized_distance * 18)`
- `form_score = clamp(100 - p70(|angle_delta_deg|) * 2.1)`
- `consistency_score = clamp(100 - std(rep_top_mags) * 3.0)`
- `vertical_axis_score = clamp(100 - vertical_axis_delta_deg * 2.8)`

Neu `camera_view_mismatch = true`:
- ep `vertical_axis_score = 70.0` (giam tac dong phat oan do goc may)

### 5.2 Cong thuc tong
`overall = 0.30*similarity + 0.28*form + 0.18*consistency + 0.14*tempo + 0.10*vertical_axis`

### 5.3 Xep hang
- `< 58`: D
- `< 72`: C
- `< 85`: B
- con lai: A

### 5.4 Axis hint
- Neu `camera_view_mismatch`: canh bao khac goc may, chi so truc dung chi tham khao.
- Else neu `vertical_axis_delta_deg >= 16`: lech nhieu.
- Else neu `>= 9`: lech nhe.
- Else: kha khop.

`axis_hint` duoc chen vao `action_items` neu:
- `camera_view_mismatch = true` hoac
- `vertical_axis_delta_deg >= 9`.

`action_items` gioi han 5 muc.

Ref: `main.py` dong ~1180-1265.

## 6) Logic truc dung/moc so sanh

### 6.1 Lech truc dung
Ham: `_vertical_axis_delta_deg(...)`
- Dang dung do nghieng truc than 2D (x/y) thay vi goc 3D thuần.
- Muc tieu: giam nhieu do chieu sau `z`, bam sat cam nhan thi giac.

### 6.2 Phat hien khac goc may
Ham: `_camera_view_mismatch_from_path(...)`
- Tren `sample_path`, lay chenh lech nghieng than 2D tung cap frame.
- Dieu kien mismatch:
- it nhat 12 mau hop le
- `median(tilt_diff) >= 18 deg`
- `std(tilt_diff) <= 7 deg`

Ref: `main.py` dong ~1423-1445.

## 7) Logic mirror trai/phai

Trong `_analyze_segment(...)`:
- Tao 2 candidate:
- student goc
- student mirror (lat x + doi cap left/right landmark)
- Chay toan bo alignment cho ca 2.
- Chon candidate co `normalized_distance` nho hon.
- Tra co `mirror_aligned` ra `reference_plane` de UI hien thi.

Ref:
- Mirror transform: `main.py` dong ~1287-1303
- Chon candidate: `main.py` khoang ~3678-3706, ~3818-3826

## 8) Du lieu nhan xet tra ve segment

Trong output segment:
- `top_issues`
- `feedback` (feature-level)
- `scoring` (overall + sub-scores + action_items)
- `reference_plane`:
- `vertical_axis_delta_deg`
- `camera_view_mismatch`
- `mirror_aligned`
- `note` (axis_hint)
- `joint_analyses`
- `top_joint_issues`
- `frame_analyses`
- `rep_feedback`

Ref: `main.py` dong ~3806-3854.

## 9) Hien thi nhan xet tren frontend

Trong `renderPostAnalysis(...)`:
- Hien thi similarity/distance.
- Hien thi diem ky thuat + cac thanh phan (form/consistency/tempo/truc dung).
- Hien thi moc so sanh truc dung + nhan:
- `(khac goc may)` neu `camera_view_mismatch`
- thong bao mirror neu `mirror_aligned`
- Hien thi `Goi y sua nhanh` tu `score.action_items`.
- Hien thi bang `joint_analyses` va text tu `rep_feedback`.

Ref: `app/web/static/js/main.js` dong ~1056-1119.
