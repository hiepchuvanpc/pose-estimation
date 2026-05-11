# Architecture - Mobile Ready

## Muc tieu

Xay dung he thong danh gia dong tac co the dung ngay cho web, va chuyen sang mobile voi chi phi thap.

## Kieu kien truc

Hexagonal theo huong domain-core:

- Domain layer (motion_core): readiness score, feature extraction, DTW, feedback logic.
- Application layer: use-case wrappers (se bo sung sau).
- Interface layer (motion_api): REST endpoints + schema.
- Client layer: web app, mobile app (Flutter/React Native/native).

## Hop dong du lieu on dinh

Cung mot schema keypoint cho moi client:

- keypoints[name] = {x, y, score}
- frame_width, frame_height
- timestamp_ms (de bo sung)
- tracking_id (de bo sung)

Version schema qua duong dan API:

- /v1/readiness
- /v1/align
- /v2/... (khi thay doi lon)

## Vi sao de chuyen mobile

- Algorithm khong dinh vao framework.
- API contract on dinh, mobile goi truc tiep.
- Co the dat motion_core len edge service, mobile chi xu ly camera + upload feature.
- Co the doi transport REST -> gRPC sau ma khong doi domain logic.

## Quyet dinh quan trong ngay tu dau

- Chuan hoa he toa do keypoint (pixels hay normalized 0..1) va giu nhat quan.
- Chot naming keypoints theo mot bo xuyen suot.
- Luu metadata pose-estimator version de debug sai lech.
- Tach scoring logic theo module de A/B test de dang.
