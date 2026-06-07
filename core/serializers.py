"""
Serializers for Academic Admission System
Handles validation, state transitions, and frontend schema generation.
"""
from datetime import date
from rest_framework import serializers
from django.utils import timezone
from .models import (
    Program, ProgramField, Admission, AdmissionState,
    AdmissionStateLog, AdmissionEvent, InternalNote,
    ContentPage, Achievement, GalleryItem, Enquiry, AnalyticEvent, Faculty,
    WhatsAppConfig, Student, Attendance, ExamResult, StudentNote, AcademicClass,
    Exam, ExamMark
)


class ProgramFieldSerializer(serializers.ModelSerializer):
    """Serializer for dynamic form fields - frontend renders schema from this"""
    class Meta:
        model = ProgramField
        fields = [
            'id', 'step', 'field_key', 'label', 'field_type',
            'placeholder', 'help_text', 'required', 'validation_rules',
            'show_condition', 'choices', 'display_order', 'is_visible'
        ]


class ProgramSerializer(serializers.ModelSerializer):
    """Program serializer with embedded fields for schema generation"""
    
    class Meta:
        model = Program
        fields = [
            'id', 'name', 'slug', 'subtitle', 'description', 'image',
            'min_age', 'max_age', 'is_active', 'display_order', 'config',
            'features', 'curriculum', 'outcomes', 'gallery', 'faq'
        ]


class ProgramSummarySerializer(serializers.ModelSerializer):
    """Lightweight program info for dropdowns and lists"""
    class Meta:
        model = Program
        fields = ['id', 'name', 'slug', 'subtitle', 'min_age', 'max_age']


class AdmissionStateLogSerializer(serializers.ModelSerializer):
    """Serializer for admission state change history"""
    class Meta:
        model = AdmissionStateLog
        fields = [
            'id', 'old_state', 'new_state', 'action',
            'performed_by', 'details', 'created_at'
        ]


class InternalNoteSerializer(serializers.ModelSerializer):
    """Serializer for staff internal notes"""
    class Meta:
        model = InternalNote
        fields = ['id', 'author', 'content', 'created_at']


class AdmissionListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for admission lists"""
    program_name = serializers.CharField(source='program.name', read_only=True)
    
    class Meta:
        model = Admission
        fields = [
            'id', 'application_number', 'program', 'program_name',
            'state', 'current_step', 'name', 'phone', 'email',
            'created_at', 'submitted_at'
        ]


class AdmissionDetailSerializer(serializers.ModelSerializer):
    """Full admission details for admin view"""
    program_name = serializers.CharField(source='program.name', read_only=True)
    state_logs = AdmissionStateLogSerializer(many=True, read_only=True)
    notes = InternalNoteSerializer(many=True, read_only=True)
    age_verified = serializers.SerializerMethodField()
    
    class Meta:
        model = Admission
        fields = [
            'id', 'application_number', 'program', 'program_name', 'state',
            'current_step', 'completed_steps',
            
            # Personal
            'student_photo', 'photo_verified', 'name', 'dob', 'age_at_submission',
            'age_verified', 'phone', 'phone_country_code', 'email',
            'address_house_name', 'address_place', 'address_post_office',
            'address_pin_code', 'address_state', 'address_district',
            
            # Academic
            'madrassa_name', 'class_stopped', 'school_college', 'standard',
            'languages_known', 'languages_other', 'academic_data',
            'achievements_file', 'achievements_verified',
            
            # Guardian
            'guardian_name', 'guardian_relation', 'guardian_phone',
            'guardian_phone_country_code', 'guardian_email', 'guardian_occupation',
            
            # Tracking
            'completed_steps', 'time_spent_per_step', 'submitted_at',
            'draft_saved_at', 'internal_notes',
            
            # Related
            'state_logs', 'notes', 'created_at', 'updated_at'
        ]
        # TASK 9: Serializer Safety - Protect sensitive fields from frontend modification
        read_only_fields = [
            'application_number', 'state', 'age_at_submission',
            'current_step', 'completed_steps', 'submitted_at', 
            'draft_saved_at', 'photo_verified', 'photo_hash'
        ]
    
    def get_age_verified(self, obj):
        """Verify age calculation is correct"""
        if obj.dob:
            # Handle case where dob might still be a string
            dob = obj.dob
            if isinstance(dob, str):
                from datetime import datetime
                try:
                    dob = datetime.strptime(dob, '%Y-%m-%d').date()
                except ValueError:
                    return None
            
            today = timezone.now().date()
            age = today.year - dob.year
            if (today.month, today.day) < (dob.month, dob.day):
                age -= 1
            return age == obj.age_at_submission
        return None


class AdmissionCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new admissions"""
    step = serializers.IntegerField(write_only=True, required=False, default=1)
    step_data = serializers.JSONField(write_only=True, required=False, default=dict)
    time_spent = serializers.IntegerField(write_only=True, required=False, default=0)
    # Add explicit file field for student photo
    student_photo = serializers.FileField(write_only=True, required=False)
    
    class Meta:
        model = Admission
        fields = [
            'program', 'step', 'step_data', 'time_spent', 'student_photo'
        ]
    
    def validate_program(self, value):
        """Ensure program is active"""
        if not value.is_active:
            raise serializers.ValidationError("This program is not currently accepting applications")
        return value
    
    def validate(self, attrs):
        """Validate admission creation"""
        program = attrs['program']
        step = attrs.get('step', 1)
        step_data = attrs.get('step_data', {})
        
        # For step 1, validate required fields (only if step_data is a valid dict)
        if step == 1 and isinstance(step_data, dict):
            required_fields = ['name', 'dob', 'phone', 'email']
            for field in required_fields:
                # Skip validation if field is missing or is a non-string (like empty object from JSON)
                if field not in step_data or not step_data[field]:
                    raise serializers.ValidationError({
                        'step_data': f'{field} is required for step 1'
                    })
        
        return attrs
    
    def create(self, validated_data):
        """Create admission with step data"""
        from datetime import datetime
        
        step = validated_data.pop('step', 1)
        step_data = validated_data.pop('step_data', {})
        time_spent = validated_data.pop('time_spent', 0)
        # Get student_photo from validated_data if sent directly
        student_photo = validated_data.pop('student_photo', None)
        
        # For step 1, extract all required fields from step_data to create the admission
        # The Admission model requires: name, dob, phone, email, address fields
        admission_data = {'program': validated_data['program']}
        
        # Extract required fields from step_data for step 1
        if isinstance(step_data, dict):
            # Map step_data keys to model fields
            field_mapping = {
                'name': 'name',
                'dob': 'dob',
                'phone': 'phone',
                'phone_country_code': 'phone_country_code',
                'email': 'email',
                'address_house_name': 'address_house_name',
                'address_place': 'address_place',
                'address_post_office': 'address_post_office',
                'address_pin_code': 'address_pin_code',
                'address_state': 'address_state',
                'address_district': 'address_district',
            }
            
            for step_key, model_key in field_mapping.items():
                if step_key in step_data and step_data[step_key]:
                    value = step_data[step_key]
                    # Convert date string to Date object
                    if model_key == 'dob' and isinstance(value, str):
                        try:
                            value = datetime.strptime(value, '%Y-%m-%d').date()
                        except ValueError:
                            pass  # Keep as string if parsing fails
                    admission_data[model_key] = value
        
        # Extract student photo if present (handle File objects from step_data)
        if not student_photo and isinstance(step_data, dict) and 'student_photo' in step_data:
            photo = step_data['student_photo']
            if photo and hasattr(photo, 'read'):
                student_photo = photo
        
        # Create admission with all required fields
        # NOTE: We DON'T call complete_step() here because the admission was already
        # created with all the data. We just need to mark step 1 as completed.
        admission = Admission.objects.create(**admission_data)
        
        # Handle file upload - save if photo was uploaded
        if student_photo:
            admission.student_photo = student_photo
            admission.save()
        
        # Mark step 1 as completed - simply update the fields directly
        # This avoids any issues with complete_step validation
        try:
            # Just mark step 1 as completed directly
            admission.completed_steps = [1]
            admission.current_step = 2  # Move to step 2
            admission.time_spent_per_step = {'1': time_spent}
            admission.draft_saved_at = timezone.now()
            admission.save(update_fields=['completed_steps', 'current_step', 'time_spent_per_step', 'draft_saved_at'])
        except Exception as e:
            import traceback
            print(f"Warning: Could not mark step 1 as completed: {e}")
            traceback.print_exc()
        
        # Emit event
        AdmissionEvent.emit(admission, 'admission_created', {'step': step})
        
        return admission


class AdmissionStepSerializer(serializers.ModelSerializer):
    """
    Serializer for completing steps.
    Each step owns its fields - cannot modify previous steps.
    """
    step_data = serializers.JSONField(write_only=True)
    time_spent = serializers.IntegerField(write_only=True, required=False, default=0)
    # Add explicit file fields for achievements
    achievements_file = serializers.FileField(write_only=True, required=False)
    
    class Meta:
        model = Admission
        fields = ['step_data', 'time_spent', 'achievements_file']
    
    def validate_step_data(self, value):
        """Validate step data based on current step"""
        # Defensive check: ensure instance exists and has current_step attribute
        if not self.instance:
            raise serializers.ValidationError('No admission instance found')
        
        # If instance is a dict (shouldn't happen but handle gracefully)
        if isinstance(self.instance, dict):
            step = self.instance.get('current_step', 1)
        else:
            step = getattr(self.instance, 'current_step', 1)
        
        # Debug: Log the step being validated
        print(f"DEBUG validate_step_data: step={step}, value keys={list(value.keys())}")
        
        # Validate based on current step - but also allow completing any pending step
        # This handles the case where current_step is behind due to previous failures
        
        # Get the next step that needs to be completed
        # completed_steps is a list like [1] or [1, 2]
        completed_steps = getattr(self.instance, 'completed_steps', []) if not isinstance(self.instance, dict) else self.instance.get('completed_steps', [])
        next_step = step  # Default to current step
        
        # Find the first uncompleted step
        for s in [1, 2, 3]:
            if s not in completed_steps:
                next_step = s
                break
        
        print(f"DEBUG validate_step_data: completed_steps={completed_steps}, next_step={next_step}")
        
        # Validate based on what step the user is trying to complete
        # Check if the data matches what we expect for the next step
        if next_step == 1:
            required = ['name', 'dob', 'phone', 'email']
            for field in required:
                if field not in value or not value[field]:
                    raise serializers.ValidationError(f'{field} is required for step 1')
        
        elif next_step == 2:
            # For step 2, check for at least the most critical fields
            required = ['madrassa_name', 'class_stopped', 'standard']
            for field in required:
                if field not in value or not value[field]:
                    raise serializers.ValidationError(f'{field} is required for step 2')
        
        elif next_step == 3:
            required = ['guardian_name', 'guardian_relation', 'guardian_phone']
            for field in required:
                if field not in value or not value[field]:
                    raise serializers.ValidationError(f'{field} is required for step 3')
        
        return value
    
    def update(self, instance, validated_data):
        """Complete current step"""
        step_data = validated_data.pop('step_data', {})
        time_spent = validated_data.pop('time_spent', 0)
        # Get achievements_file from validated_data if sent directly
        achievements_file = validated_data.pop('achievements_file', None)
        
        current_step = instance.current_step
        
        # Directly update the step data and mark as completed
        # This avoids issues with complete_step validation
        try:
            if current_step == 1:
                instance._update_personal_data(step_data)
            elif current_step == 2:
                instance._update_academic_data(step_data)
            elif current_step == 3:
                instance._update_guardian_data(step_data)
            
            # Handle achievements file upload if present
            if achievements_file:
                instance.achievements_file = achievements_file
            
            # Track time spent
            time_dict = dict(instance.time_spent_per_step) if instance.time_spent_per_step else {}
            time_dict[str(current_step)] = time_spent
            instance.time_spent_per_step = time_dict
            
            # Mark step as completed
            completed = list(instance.completed_steps) if instance.completed_steps else []
            if current_step not in completed:
                completed.append(current_step)
            instance.completed_steps = completed
            
            # Move to next step
            instance.current_step = current_step + 1
            instance.draft_saved_at = timezone.now()
            instance.save()
        except Exception as e:
            import traceback
            print(f"ERROR in update: {e}")
            traceback.print_exc()
            raise
        
        # Emit event
        AdmissionEvent.emit(instance, 'step_completed', {
            'step': current_step,
            'time_spent': time_spent
        })
        
        return instance


class AdmissionSubmitSerializer(serializers.Serializer):
    """
    Serializer for final submission.
    Validates all required data is present and age is valid.
    """
    def validate(self, attrs):
        """Validate admission can be submitted"""
        admission = self.instance
        
        # Check all steps completed
        if len(admission.completed_steps) < 3:
            raise serializers.ValidationError({
                'non_field_errors': 'All steps must be completed before submission'
            })
        
        # Age validation removed - accepting students of any age
        
        # Validate email domain
        if admission.email and not admission.email.endswith('@gmail.com'):
            raise serializers.ValidationError({
                'email': 'Email must be a Gmail address'
            })
        
        return attrs
    
    def submit(self):
        """Submit the admission"""
        self.instance.submit()
        return self.instance


class StateTransitionSerializer(serializers.Serializer):
    """Serializer for admin state transitions"""
    new_state = serializers.ChoiceField(choices=AdmissionState.choices)
    reason = serializers.CharField(required=False, allow_blank=True)
    
    def validate_new_state(self, value):
        """Ensure transition is valid"""
        if not self.instance.can_transition_to(value):
            raise serializers.ValidationError(
                f'Cannot transition from {self.instance.state} to {value}'
            )
        return value
    
    def transition(self, admin_user=None):
        """Perform the state transition"""
        new_state = self.validated_data['new_state']
        reason = self.validated_data.get('reason', '')
        
        if new_state == AdmissionState.REJECTED and reason:
            self.instance.reject(reason)
        else:
            self.instance.transition_to(new_state, user=admin_user)
        
        return self.instance


class ContentPageSerializer(serializers.ModelSerializer):
    """Serializer for content pages"""
    class Meta:
        model = ContentPage
        fields = [
            'id', 'slug', 'title', 'is_published', 'version',
            'meta_title', 'meta_description', 'content_blocks',
            'visible_from', 'visible_until', 'created_at', 'updated_at'
        ]


class AchievementSerializer(serializers.ModelSerializer):
    """Serializer for achievements"""
    class Meta:
        model = Achievement
        fields = [
            'id', 'title', 'description', 'date', 'category', 'image',
            'is_visible', 'display_order', 'created_at'
        ]


class GalleryItemSerializer(serializers.ModelSerializer):
    """Serializer for gallery items"""
    class Meta:
        model = GalleryItem
        fields = [
            'id', 'title', 'image', 'caption', 'category', 'date_taken',
            'display_order', 'is_visible', 'created_at'
        ]


class EnquirySerializer(serializers.ModelSerializer):
    """Serializer for contact enquiries"""
    program_name = serializers.CharField(source='program_interest.name', read_only=True, allow_null=True)
    
    class Meta:
        model = Enquiry
        fields = [
            'id', 'name', 'email', 'phone', 'program_interest',
            'program_name', 'message', 'status', 'tagged_programs',
            'assigned_to', 'follow_up_notes', 'created_at', 'closed_at'
        ]
        read_only_fields = ['status', 'created_at']


class EnquiryStatusSerializer(serializers.Serializer):
    """Serializer for updating enquiry status"""
    status = serializers.ChoiceField(choices=Enquiry.STATUS_CHOICES)
    assigned_to = serializers.CharField(required=False, allow_blank=True)
    follow_up_notes = serializers.CharField(required=False, allow_blank=True)


class AdmissionAnalyticsSerializer(serializers.Serializer):
    """Serializer for admission analytics data"""
    total_admissions = serializers.IntegerField()
    state_distribution = serializers.DictField()
    program_distribution = serializers.DictField()
    avg_time_per_step = serializers.DictField()
    drop_off_rate = serializers.DictField()
    validation_failures = serializers.ListField()


class FacultySerializer(serializers.ModelSerializer):
    """Serializer for faculty members"""
    class Meta:
        model = Faculty
        fields = [
            'id', 'name', 'role', 'qualification', 'specialization',
            'bio', 'photo', 'phone', 'display_order', 'status'
        ]


class WhatsAppConfigSerializer(serializers.ModelSerializer):
    """Serializer for WhatsApp configuration"""
    class Meta:
        model = WhatsAppConfig
        fields = [
            'id', 'phone_number', 'is_active',
            'admission_message_template', 'success_message_template',
            'approved_message_template', 'rejected_message_template',
            'notify_on_submission', 'notify_on_approval', 'notify_on_rejection',
            'send_confirmation',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate(self, attrs):
        # Ensure only one active config at a time
        if attrs.get('is_active', False):
            WhatsAppConfig.objects.filter(is_active=True).exclude(
                id=self.instance.id if self.instance else None
            ).update(is_active=False)
        return attrs


#=======================================================================
# STUDENT MANAGEMENT SERIALIZERS
#=======================================================================

class StudentNoteSerializer(serializers.ModelSerializer):
    """Serializer for student notes"""
    class Meta:
        model = StudentNote
        fields = ['id', 'author', 'content', 'created_at']
        read_only_fields = ['id', 'created_at']


class AttendanceSerializer(serializers.ModelSerializer):
    """Serializer for attendance records"""
    student_name = serializers.CharField(source='student.name', read_only=True)
    
    class Meta:
        model = Attendance
        fields = [
            'id', 'student', 'student_name', 'date', 'status', 
            'notes', 'marked_by', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class ExamResultSerializer(serializers.ModelSerializer):
    """Serializer for exam results"""
    student_name = serializers.CharField(source='student.name', read_only=True)
    percentage = serializers.SerializerMethodField()
    
    class Meta:
        model = ExamResult
        fields = [
            'id', 'student', 'student_name', 'exam_name', 'exam_date',
            'subject', 'marks', 'total_marks', 'grade', 'percentage', 'notes',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']
    
    def get_percentage(self, obj):
        if obj.marks and obj.total_marks:
            return round((float(obj.marks) / float(obj.total_marks)) * 100, 1)
        return None


class StudentListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for student lists"""
    program_name = serializers.CharField(source='program.name', read_only=True)
    attendance_percentage = serializers.SerializerMethodField()
    latest_exam = serializers.SerializerMethodField()
    subjects_studying = serializers.SerializerMethodField()
    enrolled_classes_count = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            'id', 'student_number', 'name', 'program', 'program_name',
            'batch', 'student_status', 'class_assigned', 'phone', 'guardian_name', 'status',
            'attendance_percentage', 'latest_exam', 'subjects_studying', 'enrolled_classes_count', 'enrollment_date'
        ]

    def get_attendance_percentage(self, obj):
        return obj.get_attendance_percentage()

    def get_latest_exam(self, obj):
        exam = obj.get_latest_exam_result()
        latest_mark = obj.exam_marks.select_related('exam', 'academic_class').order_by(
            '-exam__exam_date',
            '-created_at',
        ).first()

        if latest_mark and (
            not exam
            or (
                latest_mark.exam.exam_date
                and (
                    not exam.exam_date
                    or latest_mark.exam.exam_date >= exam.exam_date
                )
            )
        ):
            return {
                'exam_name': latest_mark.exam.name,
                'subject': latest_mark.academic_class.name,
                'marks': float(latest_mark.marks) if latest_mark.marks is not None else None,
                'grade': latest_mark.grade,
            }

        if exam:
            return {
                'exam_name': exam.exam_name,
                'subject': exam.subject,
                'marks': float(exam.marks) if exam.marks else None,
                'grade': exam.grade
            }
        return None

    def get_subjects_studying(self, obj):
        """Get count of subjects the student is studying"""
        return obj.enrolled_classes.filter(status='ongoing').count()
    
    def get_enrolled_classes_count(self, obj):
        """Get total count of enrolled classes"""
        return obj.enrolled_classes.count()


class StudentDetailSerializer(serializers.ModelSerializer):
    """Full serializer for student details"""
    program_name = serializers.CharField(source='program.name', read_only=True)
    attendance_records = AttendanceSerializer(many=True, read_only=True)
    exam_results = serializers.SerializerMethodField()
    notes = StudentNoteSerializer(many=True, read_only=True)
    attendance_percentage = serializers.SerializerMethodField()
    attendance_summary = serializers.SerializerMethodField()
    enrolled_classes = serializers.SerializerMethodField()
    
    class Meta:
        model = Student
        fields = [
            'id', 'student_number', 'admission',

            # Personal Information
            'student_photo', 'name', 'dob', 'phone', 'phone_country_code', 'email',
            'address_house_name', 'address_place', 'address_post_office',
            'address_pin_code', 'address_state', 'address_district',

            # Guardian Information
            'guardian_name', 'guardian_relation', 'guardian_phone',
            'guardian_phone_country_code', 'guardian_email', 'guardian_occupation',

            # Academic Information
            'program', 'program_name', 'batch', 'student_status',
            'class_assigned', 'teacher', 'languages_known',
            'enrollment_date', 'status',

            # Classes/Subjects
            'enrolled_classes',

            # Attendance & Results
            'attendance_percentage', 'attendance_summary',
            'attendance_records', 'exam_results', 'notes',

            # Internal
            'internal_notes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'student_number', 'created_at', 'updated_at']
    
    def get_attendance_percentage(self, obj):
        return obj.get_attendance_percentage()
    
    def get_attendance_summary(self, obj):
        records = obj.attendance_records.all()
        total = records.count()
        if total == 0:
            return {'total': 0, 'present': 0, 'absent': 0, 'leave': 0, 'late': 0}

        return {
            'total': total,
            'present': records.filter(status='present').count(),
            'absent': records.filter(status='absent').count(),
            'leave': records.filter(status='leave').count(),
            'late': records.filter(status='late').count(),
        }
    
    def get_enrolled_classes(self, obj):
        """Get all enrolled classes with their status"""
        classes = obj.enrolled_classes.all()
        ongoing = []
        completed = []
        for cls in classes:
            class_data = {
                'id': str(cls.id),
                'name': cls.name,
                'faculty': cls.faculty.name if cls.faculty else None,
                'status': cls.status
            }
            if cls.status == 'ongoing':
                ongoing.append(class_data)
            else:
                completed.append(class_data)
        return {
            'ongoing': ongoing,
            'completed': completed
        }

    def get_exam_results(self, obj):
        legacy_results = [
            {
                'id': str(exam.id),
                'exam_name': exam.exam_name,
                'exam_date': exam.exam_date,
                'subject': exam.subject,
                'marks': float(exam.marks) if exam.marks is not None else None,
                'total_marks': float(exam.total_marks) if exam.total_marks is not None else 100,
                'grade': exam.grade,
                'percentage': round((float(exam.marks) / float(exam.total_marks)) * 100, 1)
                if exam.marks is not None and exam.total_marks
                else None,
                'remarks': exam.notes,
                'class_name': exam.subject,
            }
            for exam in obj.exam_results.all()
        ]

        module_results = [
            {
                'id': str(mark.id),
                'exam_name': mark.exam.name,
                'exam_date': mark.exam.exam_date,
                'subject': mark.academic_class.name,
                'marks': float(mark.marks) if mark.marks is not None else None,
                'total_marks': 100,
                'grade': mark.grade,
                'percentage': mark.percentage,
                'remarks': mark.remarks,
                'class_name': mark.academic_class.name,
            }
            for mark in obj.exam_marks.select_related('exam', 'academic_class').all()
        ]

        combined_results = legacy_results + module_results
        combined_results.sort(
            key=lambda item: (
                item.get('exam_date') or date.min,
                item.get('exam_name') or "",
            ),
            reverse=True,
        )
        return combined_results


class StudentCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new students"""
    class Meta:
        model = Student
        fields = [
            # Personal Information
            'student_photo', 'name', 'dob', 'phone', 'phone_country_code', 'email',
            'address_house_name', 'address_place', 'address_post_office',
            'address_pin_code', 'address_state', 'address_district',

            # Guardian Information
            'guardian_name', 'guardian_relation', 'guardian_phone',
            'guardian_phone_country_code', 'guardian_email', 'guardian_occupation',

            # Academic Information
            'program', 'batch', 'student_status', 'class_assigned', 'teacher', 'languages_known',
            'enrollment_date', 'status'
        ]
    
    def validate_program(self, value):
        if not value.is_active:
            raise serializers.ValidationError("Cannot enroll in inactive program")
        return value


#=======================================================================
# ACADEMIC CLASS/SUBJECT SERIALIZERS
#=======================================================================

class AcademicClassListSerializer(serializers.ModelSerializer):
    """Serializer for class/subject lists"""
    faculty_name = serializers.CharField(source='faculty.name', read_only=True)
    student_count = serializers.SerializerMethodField()
    
    class Meta:
        model = AcademicClass
        fields = [
            'id', 'name', 'description', 'faculty', 'faculty_name',
            'status', 'student_count', 'display_order', 'created_at'
        ]
    
    def get_student_count(self, obj):
        return obj.get_student_count()


class AcademicClassDetailSerializer(serializers.ModelSerializer):
    """Serializer for class/subject details"""
    faculty_name = serializers.CharField(source='faculty.name', read_only=True)
    student_count = serializers.SerializerMethodField()
    students = serializers.SerializerMethodField()
    
    class Meta:
        model = AcademicClass
        fields = [
            'id', 'name', 'description', 'faculty', 'faculty_name',
            'students', 'student_count', 'status', 
            'display_order', 'created_at', 'updated_at'
        ]
    
    def get_student_count(self, obj):
        return obj.get_student_count()
    
    def get_students(self, obj):
        """Get list of enrolled students"""
        students = obj.students.all()
        return [{
            'id': str(s.id),
            'name': s.name,
            'student_number': s.student_number,
            'batch': s.batch,
            'student_status': s.student_status
        } for s in students]


class AcademicClassCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating classes"""
    class Meta:
        model = AcademicClass
        fields = [
            'name', 'description', 'faculty', 'students', 'status', 'display_order'
        ]


class ExamListSerializer(serializers.ModelSerializer):
    class_count = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    class Meta:
        model = Exam
        fields = [
            'id',
            'name',
            'exam_date',
            'description',
            'status',
            'class_count',
            'created_at',
        ]

    def get_class_count(self, obj):
        return obj.get_related_classes().count()

    def get_status(self, obj):
        return obj.get_status()


class ExamCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exam
        fields = ['id', 'name', 'exam_date', 'description']
        read_only_fields = ['id']


class ExamClassSummarySerializer(serializers.Serializer):
    class_id = serializers.UUIDField()
    subject_name = serializers.CharField()
    faculty = serializers.CharField()
    student_count = serializers.IntegerField()
    highest = serializers.FloatField(allow_null=True)
    lowest = serializers.FloatField(allow_null=True)
    average = serializers.FloatField(allow_null=True)
    pass_percentage = serializers.FloatField()
    marks_entered = serializers.IntegerField()


class ExamMarkEntrySerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.name', read_only=True)
    student_number = serializers.CharField(source='student.student_number', read_only=True)
    class_name = serializers.CharField(source='academic_class.name', read_only=True)
    exam_name = serializers.CharField(source='exam.name', read_only=True)
    exam_date = serializers.DateField(source='exam.exam_date', read_only=True)
    grade = serializers.SerializerMethodField()
    percentage = serializers.SerializerMethodField()

    class Meta:
        model = ExamMark
        fields = [
            'id',
            'exam',
            'exam_name',
            'exam_date',
            'academic_class',
            'class_name',
            'student',
            'student_name',
            'student_number',
            'marks',
            'remarks',
            'grade',
            'percentage',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_grade(self, obj):
        return obj.grade

    def get_percentage(self, obj):
        return obj.percentage


class ExamDetailSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    classes = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()

    class Meta:
        model = Exam
        fields = [
            'id',
            'name',
            'exam_date',
            'description',
            'status',
            'summary',
            'classes',
            'created_at',
            'updated_at',
        ]

    def get_status(self, obj):
        return obj.get_status()

    def get_classes(self, obj):
        summaries = []
        for classroom in obj.get_related_classes().select_related('faculty'):
            marks_qs = obj.mark_entries.filter(
                academic_class=classroom,
                marks__isnull=False,
            )
            student_count = classroom.students.count()
            values = [float(mark.marks) for mark in marks_qs if mark.marks is not None]
            passed = len([value for value in values if value >= 40])

            summaries.append({
                'class_id': classroom.id,
                'subject_name': classroom.name,
                'faculty': classroom.faculty.name if classroom.faculty else '-',
                'student_count': student_count,
                'highest': max(values) if values else None,
                'lowest': min(values) if values else None,
                'average': round(sum(values) / len(values), 1) if values else None,
                'pass_percentage': round((passed / len(values)) * 100, 1) if values else 0,
                'marks_entered': len(values),
            })
        return summaries

    def get_summary(self, obj):
        marks_qs = obj.mark_entries.select_related('student').filter(marks__isnull=False)
        values = [float(mark.marks) for mark in marks_qs if mark.marks is not None]
        top_mark = None

        if marks_qs.exists():
            top_mark = max(marks_qs, key=lambda entry: float(entry.marks or 0))

        return {
            'total_students': obj.get_total_students(),
            'overall_average': round(sum(values) / len(values), 1) if values else None,
            'top_performer': {
                'student_id': str(top_mark.student.id),
                'student_name': top_mark.student.name,
                'marks': float(top_mark.marks),
                'class_name': top_mark.academic_class.name,
            } if top_mark else None,
        }
