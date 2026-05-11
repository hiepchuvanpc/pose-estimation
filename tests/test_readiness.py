from motion_core.readiness import ReadinessParams, readiness_score, orientation_match
from motion_core.types import Keypoint


def _frame(offset_x: float = 0.0):
    return {
        "left_shoulder": Keypoint(100 + offset_x, 120, 0.99),
        "right_shoulder": Keypoint(200 + offset_x, 120, 0.99),
        "neck": Keypoint(150 + offset_x, 130, 0.99),
        "mid_hip": Keypoint(150 + offset_x, 240, 0.99),
        "left_hip": Keypoint(130 + offset_x, 235, 0.99),
        "right_hip": Keypoint(170 + offset_x, 235, 0.99),
        "left_knee": Keypoint(130 + offset_x, 320, 0.99),
        "right_knee": Keypoint(170 + offset_x, 320, 0.99),
        "left_ankle": Keypoint(130 + offset_x, 410, 0.99),
        "right_ankle": Keypoint(170 + offset_x, 410, 0.99),
        "left_elbow": Keypoint(95 + offset_x, 180, 0.99),
        "right_elbow": Keypoint(205 + offset_x, 180, 0.99),
        "left_wrist": Keypoint(90 + offset_x, 240, 0.99),
        "right_wrist": Keypoint(210 + offset_x, 240, 0.99),
        "nose": Keypoint(150 + offset_x, 80, 0.99),
    }


def test_readiness_high_for_similar_pose():
    teacher = _frame()
    student = _frame(offset_x=5)
    params = ReadinessParams()

    total, s_view, s_comp, s_frame = readiness_score(student, teacher, 640, 480, params)

    assert total > 0.7
    assert s_view > 0.8
    assert s_comp > 0.8
    assert s_frame > 0.3


def test_orientation_match_same_direction():
    """Test that push-up position (head above hip) matches with same orientation."""
    # Both in push-up position: head (y=80) above hip (y=240)
    teacher = _frame()
    student = _frame(offset_x=5)
    
    score = orientation_match(student, teacher)
    assert score == 1.0, "Same orientation should give score 1.0"


def test_orientation_match_flipped_180():
    """Test that flipped 180 degrees (lying face-up) does NOT match push-up."""
    # Teacher: push-up position (head y=80 < hip y=240)
    teacher = _frame()
    
    # Student: flipped 180 degrees (lying face-up, head y=400 > hip y=240)
    student_flipped = {
        "left_shoulder": Keypoint(100, 360, 0.99),  # Lower than hip
        "right_shoulder": Keypoint(200, 360, 0.99),
        "neck": Keypoint(150, 350, 0.99),
        "mid_hip": Keypoint(150, 240, 0.99),  # Hip stays center
        "left_hip": Keypoint(130, 245, 0.99),
        "right_hip": Keypoint(170, 245, 0.99),
        "left_knee": Keypoint(130, 160, 0.99),  # Knees higher
        "right_knee": Keypoint(170, 160, 0.99),
        "left_ankle": Keypoint(130, 70, 0.99),  # Ankles at top
        "right_ankle": Keypoint(170, 70, 0.99),
        "left_elbow": Keypoint(95, 300, 0.99),
        "right_elbow": Keypoint(205, 300, 0.99),
        "left_wrist": Keypoint(90, 240, 0.99),
        "right_wrist": Keypoint(210, 240, 0.99),
        "nose": Keypoint(150, 400, 0.99),  # Head at bottom (y=400 > hip y=240)
    }
    
    score = orientation_match(student_flipped, teacher)
    assert score == 0.0, "Flipped 180 degrees should give score 0.0"


def test_readiness_fails_when_flipped():
    """Test that readiness score fails when student is flipped 180 degrees."""
    teacher = _frame()  # Push-up position
    
    # Student flipped (lying face-up)
    student_flipped = {
        "left_shoulder": Keypoint(100, 360, 0.99),
        "right_shoulder": Keypoint(200, 360, 0.99),
        "neck": Keypoint(150, 350, 0.99),
        "mid_hip": Keypoint(150, 240, 0.99),
        "left_hip": Keypoint(130, 245, 0.99),
        "right_hip": Keypoint(170, 245, 0.99),
        "left_knee": Keypoint(130, 160, 0.99),
        "right_knee": Keypoint(170, 160, 0.99),
        "left_ankle": Keypoint(130, 70, 0.99),
        "right_ankle": Keypoint(170, 70, 0.99),
        "left_elbow": Keypoint(95, 300, 0.99),
        "right_elbow": Keypoint(205, 300, 0.99),
        "left_wrist": Keypoint(90, 240, 0.99),
        "right_wrist": Keypoint(210, 240, 0.99),
        "nose": Keypoint(150, 400, 0.99),
    }
    
    params = ReadinessParams()
    total, s_view, s_comp, s_frame = readiness_score(student_flipped, teacher, 640, 480, params)
    
    # View score should be 0 because orientation doesn't match
    assert s_view == 0.0, "View score should be 0 when flipped 180 degrees"
    # Overall readiness should fail
    assert total < 0.7, "Total readiness should be low when flipped"
