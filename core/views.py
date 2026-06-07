from rest_framework import viewsets, permissions, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import authenticate
from django.utils import timezone
from django.db.models import Count, Q, Avg
from datetime import timedelta
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError
from .models import (
    Faculty, AcademicClass, Student, Attendance, StudentNote,
    Program, Achievement, GalleryItem, ContentPage, Enquiry, WhatsAppConfig,
    Admission, AdmissionState, AdmissionStateLog, AdmissionEvent, InternalNote
)
from .serializers import (
    ProgramSerializer, AchievementSerializer, GalleryItemSerializer,
    FacultySerializer, ContentPageSerializer, EnquirySerializer,
    AdmissionCreateSerializer, AdmissionDetailSerializer, AdmissionSubmitSerializer,
    StateTransitionSerializer, WhatsAppConfigSerializer,
    AdmissionListSerializer, AdmissionStepSerializer, InternalNoteSerializer
)


def get_faculty_from_request(request):
    """Extract faculty from X-Faculty-Token header or Authorization Bearer header."""
    token = request.headers.get('X-Faculty-Token', '').strip()
    print(f"[DEBUG] X-Faculty-Token: {token[:20] if token else 'NONE'}...")

    if not token:
        auth_header = request.headers.get('Authorization', '')
        print(f"[DEBUG] Auth: {auth_header[:30] if auth_header else 'NONE'}...")
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header[len('Bearer '):].strip()

    if not token:
        print("[DEBUG] No token")
        return None

    print(f"[DEBUG] Using token: {token[:20]}...")
    if '-' in token:
        try:
            user_id = int(token.split('-')[0])
            print(f"[DEBUG] user_id={user_id}")
            faculty = Faculty.objects.select_related('user').get(user_id=user_id)
            print(f"[DEBUG] ✓ Faculty: {faculty.name} ({faculty.id})")
            return faculty
        except Faculty.DoesNotExist:
            print(f"[ERROR] Faculty not found for user_id={user_id}")
        except Exception as e:
            print(f"[ERROR] Parse error: {e}")

    print("[DEBUG] Token auth failed")
    return None

    # Legacy token format: userid-timestamp
    if '-' in token:
        try:
            user_id = int(token.split('-')[0])
            return Faculty.objects.select_related('user').get(user_id=user_id)
        except (Faculty.DoesNotExist, ValueError, IndexError):
            pass

    # JWT fallback via simplejwt, if token is JWT type
    try:
        jwt_auth = JWTAuthentication()
        validated_token = jwt_auth.get_validated_token(token)
        user = jwt_auth.get_user(validated_token)
        return Faculty.objects.select_related('user').get(user=user)
    except (TokenError, Faculty.DoesNotExist, Exception) as e:
        # useful debug during local development
        print("[get_faculty_from_request] JWT fallback failed:", str(e))

    print("[get_faculty_from_request] faculty lookup failed for token:", token)
    return None


class FacultyLoginView(APIView):
    """Handle faculty login and token generation"""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        
        if not username or not password:
            return Response({'error': 'Username and password required'}, status=status.HTTP_400_BAD_REQUEST)
        
        user = authenticate(username=username, password=password)
        
        if user is None:
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            faculty = Faculty.objects.get(user=user)
        except Faculty.DoesNotExist:
            return Response({'error': 'Faculty not found or inactive'}, status=status.HTTP_401_UNAUTHORIZED)
        
        # Token format: userid-timestamp (no "Bearer" to avoid JWT interception)
        token = f"{user.id}-{timezone.now().timestamp()}"
        
        return Response({
            'token': token,
            'faculty_id': str(faculty.id),
            'username': user.username,
            'name': faculty.name,
        })


class FacultyProfileView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        faculty = get_faculty_from_request(request)
        if not faculty:
            return Response({'error': 'Invalid token'}, status=status.HTTP_401_UNAUTHORIZED)
        
        return Response({
            'id': str(faculty.id),
            'name': faculty.name,
            'email': faculty.user.email if faculty.user else '',
            'phone': faculty.phone,
            'role': faculty.role,
            'specialization': faculty.specialization,
        })


class FacultyDashboardView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        faculty = get_faculty_from_request(request)
        if not faculty:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        
        classes = AcademicClass.objects.filter(faculty=faculty)
        classes_today = classes.count()
        
        students_handled = Student.objects.filter(
            enrolled_classes__faculty=faculty
        ).distinct().count()
        
        return Response({
            'classes_today': classes_today,
            'students_handled': students_handled,
            'pending_attendance': 0,
            'avg_attendance': 85.0,
        })


class FacultyClassesView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        faculty = get_faculty_from_request(request)
        if not faculty:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        
        classes = AcademicClass.objects.filter(faculty=faculty)
        
        data = []
        for cls in classes:
            data.append({
                'id': str(cls.id),
                'name': cls.name,
                'description': cls.description,
                'student_count': cls.students.count(),
                'status': cls.status,
            })
        
        return Response(data)


class FacultyActivityView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        faculty = get_faculty_from_request(request)
        if not faculty:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        
        recent = Attendance.objects.filter(
            marked_by=str(faculty.id)
        ).select_related('student').order_by('-created_at')[:10]
        
        data = []
        for record in recent:
            data.append({
                'id': str(record.id),
                'action': f"Marked {record.student.name} as {record.status}",
                'class_name': 'Attendance',
                'created_at': record.created_at.isoformat() if record.created_at else None,
                'time_ago': self.get_time_ago(record.created_at),
            })
        
        return Response(data)
    
    def get_time_ago(self, dt):
        if not dt:
            return None
        now = timezone.now()
        diff = now - dt
        if diff.days > 0:
            return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
        if diff.seconds >= 3600:
            return f"{diff.seconds // 3600} hour{'s' if diff.seconds >= 7200 else ''} ago"
        if diff.seconds >= 60:
            return f"{diff.seconds // 60} minute{'s' if diff.seconds >= 120 else ''} ago"
        return "Just now"


class FacultyClassStudentsView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def get(self, request, class_id):
        faculty = get_faculty_from_request(request)
        if not faculty:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            cls = AcademicClass.objects.get(id=class_id, faculty=faculty)
        except AcademicClass.DoesNotExist:
            return Response({'error': 'Class not found'}, status=status.HTTP_404_NOT_FOUND)
        
        students = cls.students.all()
        
        data = []
        for student in students:
            data.append({
                'id': str(student.id),
                'name': student.name,
                'student_number': student.student_number,
                'photo': student.student_photo.url if student.student_photo else None,
            })
        
        return Response(data)


class FacultyClassAttendanceView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def get(self, request, class_id):
        faculty = get_faculty_from_request(request)
        if not faculty:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            cls = AcademicClass.objects.get(id=class_id, faculty=faculty)
        except AcademicClass.DoesNotExist:
            return Response({'error': 'Class not found'}, status=status.HTTP_404_NOT_FOUND)
        
        student_ids = cls.students.values_list('id', flat=True)
        records = Attendance.objects.filter(student_id__in=student_ids).order_by('-date')[:50]
        
        from collections import defaultdict
        by_date = defaultdict(lambda: {'present': 0, 'absent': 0, 'total': 0})
        
        for record in records:
            date_str = record.date.isoformat()
            by_date[date_str]['total'] += 1
            if record.status in by_date[date_str]:
                by_date[date_str][record.status] += 1
        
        data = []
        for date_str, counts in sorted(by_date.items(), reverse=True):
            data.append({
                'date': date_str,
                'present': counts['present'],
                'absent': counts['absent'],
                'total': counts['total'],
            })
        
        return Response(data)


class FacultyStudentDetailView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def get(self, request, student_id):
        faculty = get_faculty_from_request(request)
        if not faculty:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            student = Student.objects.get(id=student_id)
        except Student.DoesNotExist:
            return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)
        
        attendance_records = Attendance.objects.filter(student=student)
        total = attendance_records.count()
        present = attendance_records.filter(status='present').count()
        attendance_pct = (present / total * 100) if total > 0 else 0
        
        return Response({
            'id': str(student.id),
            'name': student.name,
            'student_number': student.student_number,
            'phone': student.phone,
            'email': student.email,
            'guardian_name': student.guardian_name,
            'guardian_phone': student.guardian_phone,
            'attendance_percentage': round(attendance_pct, 1),
            'enrolled_classes': [{'id': str(cls.id), 'name': cls.name} for cls in student.enrolled_classes.all()],
        })


class FacultyStudentAttendanceView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def get(self, request, student_id):
        faculty = get_faculty_from_request(request)
        if not faculty:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            student = Student.objects.get(id=student_id)
        except Student.DoesNotExist:
            return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)
        
        records = Attendance.objects.filter(student=student).order_by('-date')[:50]
        
        data = []
        for record in records:
            data.append({
                'id': str(record.id),
                'date': record.date.isoformat() if record.date else None,
                'status': record.status,
            })
        
        return Response(data)


class FacultyStudentNotesView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def get(self, request, student_id):
        faculty = get_faculty_from_request(request)
        if not faculty:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            student = Student.objects.get(id=student_id)
        except Student.DoesNotExist:
            return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)
        
        notes = StudentNote.objects.filter(student=student).order_by('-created_at')
        
        data = []
        for note in notes:
            data.append({
                'id': str(note.id),
                'content': note.content,
                'author': note.author,
                'created_at': note.created_at.isoformat(),
            })
        
        return Response(data)
    
    def post(self, request, student_id):
        faculty = get_faculty_from_request(request)
        if not faculty:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            student = Student.objects.get(id=student_id)
        except Student.DoesNotExist:
            return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)
        
        content = request.data.get('content')
        if not content:
            return Response({'error': 'Content required'}, status=status.HTTP_400_BAD_REQUEST)
        
        note = StudentNote.objects.create(student=student, author=faculty.name, content=content)
        
        return Response({
            'id': str(note.id),
            'content': note.content,
            'author': note.author,
            'created_at': note.created_at.isoformat(),
        }, status=status.HTTP_201_CREATED)


class SaveAttendanceView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def post(self, request, class_id):
        faculty = get_faculty_from_request(request)
        if not faculty:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            cls = AcademicClass.objects.get(id=class_id, faculty=faculty)
        except AcademicClass.DoesNotExist:
            return Response({'error': 'Class not found'}, status=status.HTTP_404_NOT_FOUND)
        
        attendance_data = request.data.get('attendance', [])
        date_str = request.data.get('date')
        
        if date_str:
            from datetime import datetime
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            date = timezone.now().date()
        
        created_count = 0
        for record in attendance_data:
            student_id = record.get('student')
            status_val = record.get('status', 'present')
            
            if student_id:
                Attendance.objects.update_or_create(
                    student_id=student_id,
                    date=date,
                    defaults={'status': status_val, 'marked_by': str(faculty.id)}
                )
                created_count += 1
        
        return Response({
            'message': f'Attendance saved for {created_count} students',
            'class_id': str(cls.id),
            'date': date.isoformat(),
        })


# Admin panel views
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def attendance_list(request):
    records = Attendance.objects.all()[:100]
    return Response([{
        'id': str(r.id),
        'student': str(r.student.name),
        'date': r.date.isoformat() if r.date else None,
        'status': r.status,
    } for r in records])


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def attendance_detail(request, pk):
    try:
        record = Attendance.objects.get(pk=pk)
    except Attendance.DoesNotExist:
        return Response({'error': 'Not found'}, status=404)
    return Response({
        'id': str(record.id),
        'student': str(record.student.name),
        'date': record.date.isoformat() if record.date else None,
        'status': record.status,
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def faculty_list(request):
    faculties = Faculty.objects.select_related('user').all()
    return Response([{
        'id': str(f.id),
        'name': f.name,
        'email': f.user.email if f.user else '',
        'phone': f.phone,
        'role': f.role,
        'specialization': f.specialization,
        'status': f.status,
    } for f in faculties])


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def class_list(request):
    classes = AcademicClass.objects.select_related('faculty').all()
    return Response([{
        'id': str(c.id),
        'name': c.name,
        'description': c.description,
        'faculty': str(c.faculty.name) if c.faculty else None,
        'status': c.status,
    } for c in classes])


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def class_detail(request, pk):
    try:
        cls = AcademicClass.objects.select_related('faculty').prefetch_related('students').get(pk=pk)
    except AcademicClass.DoesNotExist:
        return Response({'error': 'Not found'}, status=404)
    return Response({
        'id': str(cls.id),
        'name': cls.name,
        'description': cls.description,
        'faculty': str(cls.faculty.name) if cls.faculty else None,
        'students': [str(s.name) for s in cls.students.all()],
        'status': cls.status,
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def student_list(request):
    students = Student.objects.select_related('program').all()
    return Response([{
        'id': str(s.id),
        'name': s.name,
        'student_number': s.student_number,
        'email': s.email,
        'phone': s.phone,
        'program': s.program.name if s.program else None,
        'status': s.status,
    } for s in students])


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def student_detail(request, pk):
    try:
        student = Student.objects.select_related('program').get(pk=pk)
    except Student.DoesNotExist:
        return Response({'error': 'Not found'}, status=404)
    return Response({
        'id': str(student.id),
        'name': student.name,
        'student_number': student.student_number,
        'email': student.email,
        'phone': student.phone,
        'program': student.program.name if student.program else None,
        'status': student.status,
    })


#=
# PUBLIC API VIEWSETS
#=

class ProgramViewSet(viewsets.ReadOnlyModelViewSet):
    """Public API for Programs - list and retrieve only"""
    queryset = Program.objects.filter(is_active=True)
    serializer_class = ProgramSerializer
    permission_classes = [permissions.AllowAny]
    
    @action(detail=True, methods=['get'])
    def schema(self, request, pk=None):
        """Get program-specific form schema"""
        program = self.get_object()
        fields = program.fields.filter(is_visible=True)
        serializer = ProgramFieldSerializer(fields, many=True)
        return Response(serializer.data)


class AchievementViewSet(viewsets.ReadOnlyModelViewSet):
    """Public API for Achievements - list and retrieve only"""
    queryset = Achievement.objects.filter(is_visible=True)
    serializer_class = AchievementSerializer
    permission_classes = [permissions.AllowAny]


class GalleryViewSet(viewsets.ReadOnlyModelViewSet):
    """Public API for Gallery - list and retrieve only"""
    queryset = GalleryItem.objects.filter(is_visible=True)
    serializer_class = GalleryItemSerializer
    permission_classes = [permissions.AllowAny]
    
    @action(detail=False, methods=['get'])
    def latest(self, request):
        """Get latest gallery items"""
        latest = self.get_queryset()[:6]
        serializer = self.get_serializer(latest, many=True)
        return Response(serializer.data)


class FacultyViewSet(viewsets.ReadOnlyModelViewSet):
    """Public API for Faculty - list and retrieve only"""
    queryset = Faculty.objects.filter(status='active')
    serializer_class = FacultySerializer
    permission_classes = [permissions.AllowAny]


class ContentPageViewSet(viewsets.ReadOnlyModelViewSet):
    """Public API for Content Pages - list and retrieve only"""
    queryset = ContentPage.objects.filter(is_published=True)
    serializer_class = ContentPageSerializer
    permission_classes = [permissions.AllowAny]



class EnquiryViewSet(viewsets.GenericViewSet):
    """Public API for Enquiries - create only"""
    queryset = Enquiry.objects.all()
    serializer_class = EnquirySerializer
    permission_classes = [permissions.AllowAny]
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class AdmissionViewSet(viewsets.ModelViewSet):
    """API for Admissions - Handles both public submission and admin management"""
    queryset = Admission.objects.all()
    serializer_class = AdmissionCreateSerializer
    permission_classes = [permissions.AllowAny]
    
    def get_serializer_class(self):
        if self.action == 'list':
            return AdmissionListSerializer
        if self.action == 'retrieve':
            return AdmissionDetailSerializer
        if self.action == 'complete_step':
            return AdmissionStepSerializer
        if self.action == 'submit':
            return AdmissionSubmitSerializer
        if self.action == 'transition':
            return StateTransitionSerializer
        if self.action == 'add_note':
            return InternalNoteSerializer
        return super().get_serializer_class()

    def get_permissions(self):
        # Only create and submit and status and complete_step are public
        if self.action in ['create', 'complete_step', 'submit', 'status']:
            return [permissions.AllowAny()]
        # list, retrieve, transition, add_note require authentication
        return [permissions.IsAuthenticated()]

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        """Create new admission (Step 1)"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        admission = serializer.save()
        return Response({
            'id': str(admission.id),
            'application_number': admission.application_number,
            'current_step': admission.current_step,
            'message': 'Admission created successfully'
        }, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['post'], url_path='complete_step')
    def complete_step(self, request, pk=None):
        """Complete a step in the admission process"""
        admission = self.get_object()
        serializer = self.get_serializer(admission, data=request.data)
        serializer.is_valid(raise_exception=True)
        admission = serializer.save()
        
        return Response({
            'id': str(admission.id),
            'current_step': admission.current_step,
            'completed_steps': admission.completed_steps,
            'message': 'Step completed successfully'
        })
    
    @action(detail=True, methods=['post'], url_path='submit')
    def submit(self, request, pk=None):
        """Submit the admission"""
        admission = self.get_object()
        serializer = self.get_serializer(admission, data=request.data)
        serializer.is_valid(raise_exception=True)
        admission = serializer.submit()
        
        return Response({
            'id': str(admission.id),
            'application_number': admission.application_number,
            'state': admission.state,
            'message': 'Admission submitted successfully'
        })
    
    @action(detail=True, methods=['get'], url_path='status')
    def status(self, request, pk=None):
        """Get admission status"""
        admission = self.get_object()
        return Response({
            'id': str(admission.id),
            'application_number': admission.application_number,
            'state': admission.state,
            'current_step': admission.current_step,
            'completed_steps': admission.completed_steps,
            'submitted_at': admission.submitted_at,
        })

    @action(detail=True, methods=['post'], url_path='transition')
    def transition(self, request, pk=None):
        """Admin transition admission state"""
        admission = self.get_object()
        serializer = self.get_serializer(admission, data=request.data)
        serializer.is_valid(raise_exception=True)
        admission = serializer.transition(admin_user=request.user)
        return Response({
            'id': str(admission.id),
            'state': admission.state,
            'message': f'Transitioned to {admission.state}'
        })

    @action(detail=True, methods=['post'], url_path='add_note')
    def add_note(self, request, pk=None):
        """Add an internal note to an admission"""
        admission = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = serializer.save(admission=admission, author=str(request.user))
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class WhatsAppConfigViewSet(viewsets.GenericViewSet):
    """Public API for WhatsApp config - read only"""
    queryset = WhatsAppConfig.objects.filter(is_active=True)
    serializer_class = WhatsAppConfigSerializer
    permission_classes = [permissions.AllowAny]
    
    def list(self, request, *args, **kwargs):
        """Get active WhatsApp config"""
        config = self.get_queryset().first()
        if config:
            serializer = self.get_serializer(config)
            return Response(serializer.data)
        return Response({'message': 'No WhatsApp config found'}, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=False, methods=['post'], url_path='generate_message')
    def generate_message(self, request):
        """Generate WhatsApp message for an admission"""
        admission_id = request.data.get('admission_id')
        message_type = request.data.get('message_type', 'success')
        
        if not admission_id:
            return Response({'error': 'admission_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            from .models import Admission
            admission = Admission.objects.get(id=admission_id)
        except Admission.DoesNotExist:
            return Response({'error': 'Admission not found'}, status=status.HTTP_404_NOT_FOUND)
        
        config = WhatsAppConfig.get_active_config()
        if not config:
            return Response({'error': 'WhatsApp config not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Prepare data for message
        data = {
            'student_name': admission.name,
            'program_name': admission.program.name if admission.program else 'N/A',
            'standard': admission.standard or 'N/A',
            'phone': f"{admission.phone_country_code} {admission.phone}",
            'guardian_name': admission.guardian_name or 'N/A',
            'guardian_relation': admission.guardian_relation or 'N/A',
            'guardian_phone': f"{admission.guardian_phone_country_code} {admission.guardian_phone}" if admission.guardian_phone else 'N/A',
            'application_number': admission.application_number,
        }
        
        # Generate message based on type
        if message_type == 'success':
            message = config.format_success_message(data)
        elif message_type == 'admission':
            message = config.format_admission_message(data)
        elif message_type == 'approved':
            message = config.format_approved_message(data)
        elif message_type == 'rejected':
            message = config.format_rejected_message(data)
        else:
            message = config.format_success_message(data)
        
        # Generate WhatsApp URL
        phone_number = config.phone_number.replace('+', '').replace(' ', '')
        encoded_message = message.replace('\n', '%0A').replace(' ', '%20')
        whatsapp_url = f"https://wa.me/{phone_number}?text={encoded_message}"
        
        return Response({
            'whatsapp_url': whatsapp_url,
            'message': message
        })


class HealthCheckView(APIView):
    """Public health check endpoint"""
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        return Response({
            'status': 'healthy',
            'timestamp': timezone.now().isoformat(),
        })
