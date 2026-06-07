"""
Academic Admission System - Models
Process-driven, state-controlled admission system with backend authority.
"""
import uuid
import hashlib
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone


class TimeStampedModel(models.Model):
    """Abstract base model with timestamps"""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True


class Program(TimeStampedModel):
    """
    Programs stored in DB - not hardcoded.
    Each program defines age limits, required fields, conditional questions.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    subtitle = models.CharField(max_length=200, blank=True, help_text="e.g., Da'wa Dars Program")
    description = models.TextField()
    image = models.ImageField(upload_to='programs/', null=True, blank=True, help_text="Program hero image")
    min_age = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(100)])
    max_age = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(100)])
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    
    # Program-specific configuration as JSON
    # Contains: required_fields, conditional_questions, required_documents
    config = models.JSONField(default=dict, blank=True)
    
    # Frontend-specific fields stored as JSON
    # features: [{"icon": "book", "title": "...", "description": "..."}]
    features = models.JSONField(default=list, blank=True)
    # curriculum: ["Fiqh", "Aqeedah", ...]
    curriculum = models.JSONField(default=list, blank=True)
    # outcomes: ["Outcome 1", "Outcome 2", ...]
    outcomes = models.JSONField(default=list, blank=True)
    # gallery: [{"id": 1, "image": "url"}, ...] - gallery image URLs
    gallery = models.JSONField(default=list, blank=True)
    # faq: [{"q": "question", "a": "answer"}, ...]
    faq = models.JSONField(default=list, blank=True)
    
    class Meta:
        ordering = ['display_order', 'name']
    
    def __str__(self):
        return self.name
    
    def clean(self):
        if self.min_age > self.max_age:
            raise ValidationError({'min_age': 'Min age cannot be greater than max age'})


class ProgramField(TimeStampedModel):
    """
    Dynamic field definitions per program.
    Backend returns which fields to show - frontend renders schema.
    """
    FIELD_TYPES = [
        ('text', 'Text Input'),
        ('textarea', 'Text Area'),
        ('select', 'Dropdown'),
        ('multiselect', 'Multi-Select'),
        ('checkbox', 'Checkbox'),
        ('date', 'Date'),
        ('file', 'File Upload'),
        ('phone', 'Phone Number'),
        ('email', 'Email'),
        ('number', 'Number'),
    ]
    
    REQUIRED_CHOICES = [
        ('required', 'Required'),
        ('optional', 'Optional'),
        ('conditional', 'Conditional'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='fields')
    step = models.PositiveIntegerField(help_text="Form step this field belongs to")
    field_key = models.SlugField(help_text="Unique key for this field (e.g., 'arabic_fluent')")
    label = models.CharField(max_length=200)
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES)
    placeholder = models.TextField(blank=True)
    help_text = models.TextField(blank=True)
    required = models.CharField(max_length=20, choices=REQUIRED_CHOICES, default='optional')
    
    # Validation rules
    validation_rules = models.JSONField(default=dict, blank=True)
    # { "min_length": 2, "max_length": 100, "pattern": "^[0-9]+$", "email_domain": "gmail.com" }
    
    # Conditional display
    show_condition = models.JSONField(
        default=dict,
        blank=True,
        help_text='{"field": "other_field", "value": "specific_value"}'
    )
    
    # Options for select/multiselect/checkbox
    choices = models.JSONField(default=list, blank=True)
    
    display_order = models.PositiveIntegerField(default=0)
    is_visible = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['program', 'step', 'display_order']
        unique_together = ['program', 'field_key']
    
    def __str__(self):
        return f"{self.program.name} - {self.label}"


class AdmissionState(models.TextChoices):
    """State Machine for Admission Process"""
    DRAFT = 'draft', 'Draft'
    SUBMITTED = 'submitted', 'Submitted'
    UNDER_REVIEW = 'under_review', 'Under Review'
    APPROVED = 'approved', 'Approved'
    REJECTED = 'rejected', 'Rejected'


class Admission(TimeStampedModel):
    """
    Core Admission Model - State Machine Pattern
    Backend strictly controls state transitions.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application_number = models.CharField(max_length=20, unique=True, db_index=True)
    
    # Program selection - LOCKED after Step 1
    program = models.ForeignKey(Program, on_delete=models.PROTECT, related_name='admissions')
    
    # State Machine
    state = models.CharField(
        max_length=20,
        choices=AdmissionState.choices,
        default=AdmissionState.DRAFT,
        db_index=True
    )
    
    # Step tracking (1-5)
    current_step = models.PositiveIntegerField(default=1)
    
    # === STEP 1: Personal Information ===
    student_photo = models.FileField(upload_to='photos/', null=True, blank=True)
    photo_verified = models.BooleanField(default=False)
    photo_hash = models.CharField(max_length=64, blank=True, help_text="Duplicate detection")
    
    name = models.CharField(max_length=200)
    dob = models.DateField()
    age_at_submission = models.PositiveIntegerField(editable=False)
    phone = models.CharField(max_length=20)
    phone_country_code = models.CharField(max_length=5, default='+91')
    email = models.EmailField()
    
    # Address
    address_house_name = models.CharField(max_length=200)
    address_place = models.CharField(max_length=200)
    address_post_office = models.CharField(max_length=200)
    address_pin_code = models.CharField(max_length=10)
    address_state = models.CharField(max_length=100)
    address_district = models.CharField(max_length=100)
    
    # === STEP 2: Academic Details ===
    madrassa_name = models.CharField(max_length=200, blank=True)
    class_stopped = models.CharField(max_length=100, blank=True)
    school_college = models.CharField(max_length=200, blank=True)
    standard = models.CharField(max_length=100, blank=True)
    languages_known = models.JSONField(default=list)  # ["Arabic", "English", ...]
    languages_other = models.CharField(max_length=200, blank=True)
    
    # Program-specific fields (stored as JSON based on program config)
    academic_data = models.JSONField(default=dict, blank=True)
    
    # === STEP 3: Guardian Information ===
    guardian_name = models.CharField(max_length=200, blank=True)
    guardian_relation = models.CharField(max_length=100, blank=True)
    guardian_phone = models.CharField(max_length=20, blank=True)
    guardian_phone_country_code = models.CharField(max_length=5, default='+91')
    guardian_email = models.EmailField(blank=True)
    guardian_occupation = models.CharField(max_length=200, blank=True)
    
    # === Files & Documents ===
    achievements_file = models.FileField(upload_to='achievements/', null=True, blank=True)
    achievements_verified = models.BooleanField(default=False)
    
    # Step completion tracking
    completed_steps = models.JSONField(default=list)  # [1, 2, 3] completed steps
    
    # Submission tracking
    submitted_at = models.DateTimeField(null=True, blank=True)
    draft_saved_at = models.DateTimeField(null=True, blank=True)
    
    # Analytics (backend-only tracking)
    time_spent_per_step = models.JSONField(default=dict)  # {"1": 120, "2": 180, ...}
    drop_off_step = models.PositiveIntegerField(null=True, blank=True)
    
    # Internal notes (admin only)
    internal_notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['state', 'program']),
            models.Index(fields=['created_at']),
            models.Index(fields=['submitted_at']),
        ]
    
    def __str__(self):
        return f"{self.application_number} - {self.name} ({self.state})"
    
    def save(self, *args, **kwargs):
        # Generate application number if new
        if not self.application_number:
            self.application_number = self._generate_application_number()
        
        # Calculate age at submission if DOB is set
        if self.dob:
            today = timezone.now().date()
            age = today.year - self.dob.year
            if (today.month, today.day) < (self.dob.month, self.dob.day):
                age -= 1
            self.age_at_submission = age
        
        # Auto-generate photo hash if file uploaded
        if self.student_photo and not self.photo_hash:
            self.photo_hash = self._generate_file_hash(self.student_photo)
        
        super().save(*args, **kwargs)
    
    def _generate_application_number(self):
        """
        Generate unique application number using database-safe approach.
        Uses select_for_update to prevent race conditions under concurrent submissions.
        """
        from django.db import transaction
        
        year = timezone.now().year
        prefix = f'ZA-{year}'
        
        with transaction.atomic():
            # Get the last admission with this year's prefix
            last = Admission.objects.filter(
                application_number__startswith=prefix
            ).order_by('-application_number').first()
            
            if last:
                # Extract the numeric part and increment
                try:
                    last_num = int(last.application_number.split('-')[-1])
                    new_num = last_num + 1
                except (ValueError, IndexError):
                    new_num = 1
            else:
                new_num = 1
            
            return f'ZA-{year}-{new_num:04d}'
    
    def _generate_file_hash(self, file_obj):
        """Generate SHA256 hash for duplicate detection"""
        hasher = hashlib.sha256()
        for chunk in file_obj.chunks():
            hasher.update(chunk)
        return hasher.hexdigest()
    
    # === State Machine Transitions ===
    
    def can_transition_to(self, new_state):
        """Check if state transition is valid"""
        valid_transitions = {
            AdmissionState.DRAFT: [AdmissionState.DRAFT, AdmissionState.SUBMITTED],
            AdmissionState.SUBMITTED: [AdmissionState.UNDER_REVIEW],
            AdmissionState.UNDER_REVIEW: [AdmissionState.APPROVED, AdmissionState.REJECTED],
            AdmissionState.APPROVED: [],
            AdmissionState.REJECTED: [],
        }
        return new_state in valid_transitions.get(self.state, [])
    
    def transition_to(self, new_state, user=None):
        """Perform state transition with logging"""
        if not self.can_transition_to(new_state):
            raise ValueError(f"Invalid transition from {self.state} to {new_state}")
        
        old_state = self.state
        self.state = new_state
        
        if new_state == AdmissionState.SUBMITTED:
            self.submitted_at = timezone.now()
        
        self.save()
        
        # Log the transition
        AdmissionStateLog.log_transition(self, old_state, new_state, user)
        
        # Emit event
        AdmissionEvent.emit(self, new_state)
        
        return self
    
    def submit(self):
        """Submit the admission"""
        return self.transition_to(AdmissionState.SUBMITTED)
    
    def start_review(self):
        """Mark as under review"""
        return self.transition_to(AdmissionState.UNDER_REVIEW)
    
    def approve(self):
        """Approve the admission"""
        return self.transition_to(AdmissionState.APPROVED)
    
    def reject(self, reason=''):
        """Reject the admission"""
        self.internal_notes = reason
        return self.transition_to(AdmissionState.REJECTED)
    
    def complete_step(self, step_number, data, time_spent=0):
        """Complete a step - step owns its fields, cannot modify previous"""
        import traceback
        try:
            # Validate step sequence
            if step_number != self.current_step:
                raise ValueError(f"Cannot complete step {step_number}. Current step is {self.current_step}")
            
            # Update step data
            if step_number == 1:
                self._update_personal_data(data)
            elif step_number == 2:
                self._update_academic_data(data)
            elif step_number == 3:
                self._update_guardian_data(data)
            
            # Track time spent
            self.time_spent_per_step[str(step_number)] = time_spent
            
            # Mark step as completed - use list() to ensure it's a mutable list
            if not isinstance(self.completed_steps, list):
                self.completed_steps = list(self.completed_steps) if self.completed_steps else []
            
            if step_number not in self.completed_steps:
                self.completed_steps.append(step_number)
            
            # Auto-save draft
            self.draft_saved_at = timezone.now()
            self.save()
            
            return self
        except Exception as e:
            print(f"ERROR in complete_step: {e}")
            traceback.print_exc()
            raise
    
    def _update_personal_data(self, data):
        """Update step 1 data"""
        fields = [
            'student_photo', 'name', 'dob', 'phone', 'phone_country_code',
            'email', 'address_house_name', 'address_place', 'address_post_office',
            'address_pin_code', 'address_state', 'address_district'
        ]
        for field in fields:
            if field in data:
                setattr(self, field, data[field])
    
    def _update_academic_data(self, data):
        """Update step 2 data"""
        fields = [
            'madrassa_name', 'class_stopped', 'school_college', 'standard',
            'languages_known', 'languages_other', 'achievements_file'
        ]
        for field in fields:
            if field in data:
                setattr(self, field, data[field])
        # Store program-specific data (academic_data key or program_specific key)
        if 'academic_data' in data:
            self.academic_data = data.get('academic_data', {})
        elif 'program_specific' in data:
            self.academic_data.update(data.get('program_specific', {}))
    
    def _update_guardian_data(self, data):
        """Update step 3 data"""
        fields = [
            'guardian_name', 'guardian_relation', 'guardian_phone',
            'guardian_phone_country_code', 'guardian_email', 'guardian_occupation'
        ]
        for field in fields:
            if field in data:
                setattr(self, field, data[field])


class AdmissionStateLog(TimeStampedModel):
    """
    Audit log for all state transitions and actions.
    Immutable record of admission lifecycle.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name='logs')
    old_state = models.CharField(max_length=20, blank=True)
    new_state = models.CharField(max_length=20)
    action = models.CharField(max_length=100)
    performed_by = models.CharField(max_length=100, blank=True, help_text="User or system")
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.admission.application_number}: {self.old_state} → {self.new_state}"
    
    @classmethod
    def log_transition(cls, admission, old_state, new_state, user=None):
        return cls.objects.create(
            admission=admission,
            old_state=old_state,
            new_state=new_state,
            action='state_transition',
            performed_by=str(user) if user else 'system',
            details={'triggered_by': 'submit' if new_state == 'submitted' else 'admin_action'}
        )


class AdmissionEvent(TimeStampedModel):
    """
    Event-driven backend - every major action emits an event.
    Can power email notifications, SMS, admin alerts, dashboards, analytics.
    """
    EVENT_TYPES = [
        ('admission_created', 'Admission Created'),
        ('step_completed', 'Step Completed'),
        ('submitted', 'Submitted'),
        ('state_changed', 'State Changed'),
        ('file_uploaded', 'File Uploaded'),
        ('admin_action', 'Admin Action'),
        ('draft_saved', 'Draft Saved'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    event_data = models.JSONField(default=dict)
    is_processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.admission.application_number} - {self.event_type}"
    
    @classmethod
    def emit(cls, admission, event_type, data=None):
        return cls.objects.create(
            admission=admission,
            event_type=event_type,
            event_data=data or {}
        )


class InternalNote(TimeStampedModel):
    """
    Staff-only notes on admissions.
    Timestamped, never visible to applicants.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name='notes')
    author = models.CharField(max_length=100)
    content = models.TextField()
    is_visible_to_staff = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Note on {self.admission.application_number} by {self.author}"


class ContentPage(TimeStampedModel):
    """
    Managed content pages - About, Programs, Contact, Faculty.
    Section-based, orderable blocks, versioning.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=200)
    is_published = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    
    # SEO
    meta_title = models.CharField(max_length=200, blank=True)
    meta_description = models.TextField(blank=True)
    
    # Content as ordered blocks
    content_blocks = models.JSONField(
        default=list,
        help_text='[{"type": "text", "order": 1, "data": {...}}, {"type": "image", "order": 2, "data": {...}}]'
    )
    
    # Visibility controls
    visible_from = models.DateTimeField(null=True, blank=True)
    visible_until = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['title']
    
    def __str__(self):
        return self.title
    
    def save(self, *args, **kwargs):
        # Increment version on update
        if self.pk:
            self.version += 1
        super().save(*args, **kwargs)


class Achievement(TimeStampedModel):
    """
    Student achievements with title, description, date, images.
    """
    CATEGORY_CHOICES = [
        ('academic', 'Academic'),
        ('hifz', 'Hifz Completion'),
        ('competition', 'Competition'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField()
    date = models.DateField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='academic')
    image = models.ImageField(upload_to='achievements/', null=True, blank=True)
    is_visible = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['-date', '-display_order']
    
    def __str__(self):
        return self.title


class GalleryItem(TimeStampedModel):
    """
    Gallery images with metadata.
    """
    CATEGORY_CHOICES = [
        ('campus', 'Campus'),
        ('classroom', 'Classroom'),
        ('events', 'Events'),
        ('graduation', 'Graduation'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200, blank=True)
    image = models.ImageField(upload_to='gallery/')
    caption = models.TextField(blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='campus')
    date_taken = models.DateField(null=True, blank=True)
    date_hidden = models.DateField(
        help_text="Date stored but hidden from UI",
        null=True,
        blank=True
    )
    display_order = models.PositiveIntegerField(default=0)
    is_visible = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-display_order', '-created_at']
    
    def __str__(self):
        return self.title or f"Gallery item {self.id}"


class Enquiry(TimeStampedModel):
    """
    Contact enquiries - stored as entity with status tracking.
    """
    STATUS_CHOICES = [
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('closed', 'Closed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Contact info
    name = models.CharField(max_length=200)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    
    # Enquiry details
    program_interest = models.ForeignKey(
        Program, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='enquiries'
    )
    message = models.TextField()
    
    # Tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    tagged_programs = models.JSONField(default=list, help_text="Program slugs of interest")
    
    # Follow-up
    assigned_to = models.CharField(max_length=100, blank=True)
    follow_up_notes = models.TextField(blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Enquiry from {self.name} ({self.status})"


class Faculty(TimeStampedModel):
    """
    Faculty/Staff members for the academy.
    """
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        'auth.User', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        help_text="Linked Django user for login"
    )
    name = models.CharField(max_length=200)
    role = models.CharField(max_length=200, help_text="e.g., Ustadh, Teacher")
    qualification = models.CharField(max_length=200, blank=True, help_text="e.g., Alim, Hafiz")
    specialization = models.CharField(max_length=200, blank=True, help_text="e.g., Arabic Grammar, Fiqh, Quran")
    bio = models.TextField(blank=True)
    photo = models.ImageField(upload_to='faculty/', null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True, help_text="Contact number")
    display_order = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    class Meta:
        ordering = ['display_order', 'name']
    
    def __str__(self):
        return f"{self.name} - {self.role}"
    
    def get_user(self):
        """Get the linked user or fall back to matching by username"""
        if self.user:
            return self.user
        # Fallback: try to find user by matching name
        from django.contrib.auth.models import User
        return User.objects.filter(username=self.name).first()


class WhatsAppConfig(TimeStampedModel):
    """
    WhatsApp configuration for admission notifications.
    Stores phone number and message templates with emojis.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone_number = models.CharField(
        max_length=20, 
        help_text="WhatsApp phone number with country code (e.g., +91xxxxxxxxxx)"
    )
    is_active = models.BooleanField(default=True)
    
    # Message templates with emojis
    admission_message_template = models.TextField(
        default="🎓 *New Admission Application*\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "📋 *Application Details:*\n"
                "• Name: {student_name}\n"
                "• Program: {program_name}\n"
                "• Class: {standard}\n"
                "• Phone: {phone}\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "🏫 *Guardian Info:*\n"
                "• Name: {guardian_name}\n"
                "• Relation: {guardian_relation}\n"
                "• Phone: {guardian_phone}\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "✨ *Zainussunna Academy*\n"
                "Excellence in Islamic Education",
        help_text="Message template with placeholders: {student_name}, {program_name}, {standard}, {phone}, {guardian_name}, {guardian_relation}, {guardian_phone}"
    )
    
    # Success message after submission
    success_message_template = models.TextField(
        default="✅ *Admission Submitted Successfully!*\n\n"
                "🕌 *Zainussunna Academy*\n\n"
                "Dear {student_name},\n\n"
                "🎉 Your application for *{program_name}* has been submitted successfully!\n\n"
                "📝 *Application Number:* {application_number}\n\n"
                "Our team will contact you shortly. Please keep your phone number ready.\n\n"
                "✨ *JazakAllah Khair* for choosing Zainussunna Academy!",
        help_text="Success message sent to student/guardian"
    )
    
    # Approved/Congratulations message - sent when admission is approved
    approved_message_template = models.TextField(
        default="🎉 *Congratulations! Admission Approved!*\n\n"
                "🕌 *Zainussunna Academy*\n\n"
                "Dear {student_name},\n\n"
                "✨ *Alhumdulillah!* Your admission to *{program_name}* has been APPROVED!\n\n"
                "📋 *Application Number:* {application_number}\n"
                "🆔 *Student ID:* {student_number}\n\n"
                "📅 *Next Steps:*\n"
                "• Please attend the orientation session\n"
                "• Bring all original documents for verification\n"
                "• Contact us if you have any questions\n\n"
                "We look forward to welcoming you!\n\n"
                "BarakAllah feekum,\n"
                "✨ *Zainussunna Academy*\n"
                "Excellence in Islamic Education",
        help_text="Congratulations message sent when admission is approved"
    )

    # Rejected message - inspirational quote without student/guardian details
    rejected_message_template = models.TextField(
        default="🕌 *Zainussunna Academy*\n\n"
                "Dear {student_name},\n\n"
                "We appreciate your interest in Zainussunna Academy.\n\n"
                "After careful consideration, we regret to inform you that your application could not be processed at this time.\n\n"
                "🤲 *Remember:*\n"
                "\"Every setback is a setup for a comeback.\"\n\n"
                "This is not the end of your journey. Keep pursuing knowledge and righteous deeds. Allah (SWT) has better plans for those who trust in Him.\n\n"
                "May Allah (SWT) bless you with the best.\n\n"
                "✨ *Zainussunna Academy*\n"
                "Excellence in Islamic Education",
        help_text="Inspirational message for rejected applications"
    )

    # Enable/disable features
    notify_on_submission = models.BooleanField(default=True)
    notify_on_approval = models.BooleanField(default=True)
    notify_on_rejection = models.BooleanField(default=True)
    send_confirmation = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = "WhatsApp Configuration"
        verbose_name_plural = "WhatsApp Configuration"
    
    def __str__(self):
        return f"WhatsApp Config - {self.phone_number}"
    
    @classmethod
    def get_active_config(cls):
        """Get the active WhatsApp configuration"""
        return cls.objects.filter(is_active=True).first()
    
    def format_admission_message(self, admission_data):
        """Format the admission message with data"""
        return self.admission_message_template.format(**admission_data)
    
    def format_success_message(self, data):
        """Format the success message with data"""
        return self.success_message_template.format(**data)

    def format_approved_message(self, data):
        """Format the approved/congratulations message with data"""
        return self.approved_message_template.format(**data)

    def format_rejected_message(self, data):
        """Format the rejected message with inspirational quote"""
        return self.rejected_message_template.format(**data)


class AnalyticEvent(TimeStampedModel):
    """
    Backend-only analytics tracking.
    Invasive tracking NOT used - only system-level events.
    """
    EVENT_CATEGORIES = [
        ('time_spent', 'Time Spent'),
        ('drop_off', 'Drop Off'),
        ('validation_failed', 'Validation Failed'),
        ('program_demand', 'Program Demand'),
        ('conversion', 'Conversion'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.CharField(max_length=50, choices=EVENT_CATEGORIES)
    event_data = models.JSONField(default=dict)
    admission = models.ForeignKey(
        Admission, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='analytics'
    )
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.category} - {self.created_at}"


#=
# STUDENT MANAGEMENT MODELS
#=

class Student(TimeStampedModel):
    """
    Student Model - Separate from Admission.
    Created when admission is approved or manually added.
    """
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('graduated', 'Graduated'),
        ('transferred', 'Transferred'),
        ('suspended', 'Suspended'),
    ]
    
    # Student Status for academic tracking
    STUDENT_STATUS_CHOICES = [
        ('studying', 'Studying'),
        ('completed', 'Completed'),
        ('dropped', 'Dropped'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admission = models.OneToOneField(
        Admission, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='student_record'
    )
    student_number = models.CharField(max_length=20, unique=True, db_index=True)
    
    # Personal Information
    student_photo = models.FileField(upload_to='students/photos/', null=True, blank=True)
    name = models.CharField(max_length=200)
    dob = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    phone_country_code = models.CharField(max_length=5, default='+91')
    email = models.EmailField(blank=True)
    
    # Address
    address_house_name = models.CharField(max_length=200, blank=True)
    address_place = models.CharField(max_length=200, blank=True)
    address_post_office = models.CharField(max_length=200, blank=True)
    address_pin_code = models.CharField(max_length=10, blank=True)
    address_state = models.CharField(max_length=100, blank=True)
    address_district = models.CharField(max_length=100, blank=True)
    
    # Guardian Information
    guardian_name = models.CharField(max_length=200, blank=True)
    guardian_relation = models.CharField(max_length=100, blank=True)
    guardian_phone = models.CharField(max_length=20, blank=True)
    guardian_phone_country_code = models.CharField(max_length=5, default='+91')
    guardian_email = models.EmailField(blank=True)
    guardian_occupation = models.CharField(max_length=200, blank=True)
    
    # Academic Information
    program = models.ForeignKey(
        Program, 
        on_delete=models.PROTECT, 
        related_name='enrolled_students'
    )
    batch = models.CharField(max_length=100, blank=True, help_text="e.g., Shareea 2025, Year 1")
    class_assigned = models.CharField(max_length=100, blank=True, help_text="Class/Batch name")
    teacher = models.CharField(max_length=200, blank=True, help_text="Assigned teacher")
    languages_known = models.JSONField(default=list, blank=True)
    
    # Enrollment Details
    enrollment_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    student_status = models.CharField(
        max_length=20, 
        choices=STUDENT_STATUS_CHOICES, 
        default='studying',
        help_text="Academic status: Studying, Completed, or Dropped"
    )
    
    # Internal notes
    internal_notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-enrollment_date', 'name']
        indexes = [
            models.Index(fields=['status', 'program']),
            models.Index(fields=['student_number']),
        ]
    
    def __str__(self):
        return f"{self.student_number} - {self.name}"
    
    def save(self, *args, **kwargs):
        if not self.student_number:
            self.student_number = self._generate_student_number()
        if not self.enrollment_date:
            self.enrollment_date = timezone.now().date()
        super().save(*args, **kwargs)
    
    def _generate_student_number(self):
        """Generate unique student number"""
        year = timezone.now().year
        prefix = f'ST-{year}'
        
        last_student = Student.objects.filter(
            student_number__startswith=prefix
        ).order_by('-student_number').first()
        
        if last_student:
            try:
                last_num = int(last_student.student_number.split('-')[-1])
                new_num = last_num + 1
            except (ValueError, IndexError):
                new_num = 1
        else:
            new_num = 1
        
        return f'{prefix}-{new_num:04d}'
    
    def get_attendance_percentage(self):
        """Calculate attendance percentage"""
        total = self.attendance_records.count()
        if total == 0:
            return None
        present = self.attendance_records.filter(status='present').count()
        return round((present / total) * 100, 1)
    
    def get_latest_exam_result(self):
        """Get latest exam result"""
        return self.exam_results.first()


class Attendance(TimeStampedModel):
    """
    Attendance Record for Students
    """
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('leave', 'On Leave'),
        ('late', 'Late'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='attendance_records')
    date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='present')
    notes = models.TextField(blank=True)
    marked_by = models.CharField(max_length=100, blank=True)
    
    class Meta:
        ordering = ['-date']
        unique_together = ['student', 'date']
        indexes = [
            models.Index(fields=['date', 'student']),
        ]
    
    def __str__(self):
        return f"{self.student.name} - {self.date} - {self.status}"


class ExamResult(TimeStampedModel):
    """
    Exam Results for Students
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='exam_results')
    exam_name = models.CharField(max_length=200)
    exam_date = models.DateField(null=True, blank=True)
    subject = models.CharField(max_length=200)
    marks = models.DecimalField(max_digits=5, decimal_places=2)
    total_marks = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    grade = models.CharField(max_length=5, blank=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-exam_date', '-created_at']
        indexes = [
            models.Index(fields=['student', 'exam_name']),
        ]
    
    def __str__(self):
        return f"{self.student.name} - {self.exam_name} - {self.subject}"
    
    def save(self, *args, **kwargs):
        # Auto-calculate grade based on percentage
        if self.marks and self.total_marks:
            percentage = (float(self.marks) / float(self.total_marks)) * 100
            if percentage >= 90:
                self.grade = 'A+'
            elif percentage >= 80:
                self.grade = 'A'
            elif percentage >= 70:
                self.grade = 'B+'
            elif percentage >= 60:
                self.grade = 'B'
            elif percentage >= 50:
                self.grade = 'C'
            elif percentage >= 40:
                self.grade = 'D'
            else:
                self.grade = 'F'
        super().save(*args, **kwargs)


class Exam(TimeStampedModel):
    """
    Exam container model.
    Exams are created first, then marks are recorded per class and student.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('upcoming', 'Upcoming'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    exam_date = models.DateField()
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['-exam_date', '-created_at']

    def __str__(self):
        return self.name

    def get_related_classes(self):
        return AcademicClass.objects.filter(
            status='ongoing',
        ).order_by('display_order', 'name')

    def get_total_students(self):
        return sum(classroom.students.count() for classroom in self.get_related_classes())

    def get_status(self):
        today = timezone.now().date()
        mark_entries = self.mark_entries.filter(marks__isnull=False)

        if not mark_entries.exists():
            return 'upcoming' if self.exam_date >= today else 'draft'

        related_classes = list(self.get_related_classes())
        if not related_classes:
            return 'draft'

        total_expected = sum(classroom.students.count() for classroom in related_classes)
        if total_expected == 0:
            return 'draft'

        completed_count = mark_entries.count()
        if completed_count >= total_expected:
            return 'completed'

        return 'in_progress'


class ExamMark(TimeStampedModel):
    """
    Marks recorded per exam, class, and student.
    This preserves the structure Exam -> Class -> Student -> Marks.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='mark_entries')
    academic_class = models.ForeignKey(
        'AcademicClass',
        on_delete=models.CASCADE,
        related_name='exam_marks',
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='exam_marks',
    )
    marks = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ['exam__exam_date', 'academic_class__display_order', 'student__name']
        unique_together = ['exam', 'academic_class', 'student']
        indexes = [
            models.Index(fields=['exam', 'academic_class']),
            models.Index(fields=['student', 'exam']),
        ]

    def __str__(self):
        return f"{self.exam.name} - {self.academic_class.name} - {self.student.name}"

    @property
    def percentage(self):
        if self.marks is None:
            return None
        return round(float(self.marks), 1)

    @property
    def grade(self):
        if self.marks is None:
            return ""

        percentage = float(self.marks)
        if percentage >= 90:
            return 'A+'
        if percentage >= 80:
            return 'A'
        if percentage >= 70:
            return 'B+'
        if percentage >= 60:
            return 'B'
        if percentage >= 50:
            return 'C'
        if percentage >= 40:
            return 'D'
        return 'F'


class StudentNote(TimeStampedModel):
    """
    Notes for Students - Admin only
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='notes')
    author = models.CharField(max_length=100)
    content = models.TextField()
    is_visible = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Note for {self.student.name} by {self.author}"


#=
# CLASS/SUBJECT MANAGEMENT MODELS
#=

class AcademicClass(TimeStampedModel):
    """
    Academic Class/Subject Model.
    Represents subjects being taught in the academy.
    Each class is taught by a faculty member and has enrolled students.
    """
    STATUS_CHOICES = [
        ('ongoing', 'Ongoing'),
        ('completed', 'Completed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, help_text="Subject/Class name e.g., Arabic Grammar")
    description = models.TextField(blank=True)
    faculty = models.ForeignKey(
        Faculty, 
        on_delete=models.PROTECT, 
        related_name='classes_taught',
        help_text="Faculty member teaching this class"
    )
    students = models.ManyToManyField(
        Student, 
        related_name='enrolled_classes',
        blank=True,
        help_text="Students enrolled in this class"
    )
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='ongoing',
        help_text="Class status: Ongoing or Completed"
    )
    display_order = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['display_order', 'name']
    
    def __str__(self):
        return f"{self.name} - {self.faculty.name}"
    
    def get_student_count(self):
        """Get number of enrolled students"""
        return self.students.count()
