"""
Management command to initialize the admission system with sample data.
Run: python manage.py init_system
"""
from django.core.management.base import BaseCommand
from core.models import Program, ProgramField, ContentPage, Achievement, GalleryItem, WhatsAppConfig, Faculty


class Command(BaseCommand):
    help = 'Initialize Zainussunna Academy with sample programs and content'

    def handle(self, *args, **options):
        self.stdout.write('Initializing Zainussunna Academy Backend...\n')
        
        # Create Programs
        self.create_programs()
        
        # Create Content Pages
        self.create_content_pages()
        
        # Create Sample Achievements
        self.create_achievements()
        
        # Create Sample Gallery Items
        self.create_gallery()
        
        # Create WhatsApp Configuration
        self.create_whatsapp_config()
        
        self.stdout.write(self.style.SUCCESS('\n✓ System initialized successfully!'))

    def create_programs(self):
        self.stdout.write('Creating Programs...')
        
        # Integrated Sharee'a Program
        shareea, created = Program.objects.get_or_create(
            slug='shareea',
            defaults={
                'name': "Integrated Sharee'a",
                'subtitle': "Da'wa Dars Program",
                'description': "A comprehensive Islamic studies program centered on classical learning and guidance-oriented education. Designed to help students develop sound understanding, clarity of thought, and responsible engagement with Islamic knowledge.",
                'min_age': 10,
                'max_age': 18,
                'is_active': True,
                'display_order': 1,
                'config': {
                    'duration': '4 years',
                    'qualification': 'Higher Secondary',
                },
                'features': [
                    {
                        'icon': 'book',
                        'title': 'Classical Text Study',
                        'description': 'In-depth study of core classical Islamic texts with proper understanding and context'
                    },
                    {
                        'icon': 'structure',
                        'title': 'Mukhtasar-Based Curriculum',
                        'description': 'Structured curriculum following traditional Mukhtasar methodology for systematic learning'
                    },
                    {
                        'icon': 'guidance',
                        'title': 'Guided Learning',
                        'description': 'Personal guidance under experienced Ustads with regular evaluation and feedback'
                    },
                    {
                        'icon': 'community',
                        'title': 'Scholarly Environment',
                        'description': 'Immersive learning environment fostering academic excellence and character development'
                    }
                ],
                'curriculum': [
                    'Fiqh (Islamic Jurisprudence)',
                    'Aqeedah (Islamic Creed)',
                    'Seerah (Prophetic Biography)',
                    'Hadith Studies',
                    'Arabic Language',
                    'Usul al-Fiqh (Principles of Jurisprudence)'
                ],
                'outcomes': [
                    'Strong foundational knowledge in Islamic sciences',
                    'Ability to understand and explain classical texts',
                    'Critical thinking and analytical skills',
                    'Preparation for advanced Islamic studies',
                    'Character development and spiritual growth'
                ],
                'gallery': [],
                'faq': [
                    {
                        'q': 'Who can apply for these programs?',
                        'a': 'Students who are committed to disciplined Islamic study and have completed basic Islamic education. Both programs welcome sincere learners dedicated to gaining authentic knowledge.'
                    },
                    {
                        'q': 'What is the medium of instruction?',
                        'a': 'Primary instruction is in Arabic with guided explanation in English/Malayalam to ensure proper understanding of concepts and texts.'
                    },
                    {
                        'q': 'How are students assessed?',
                        'a': 'Regular evaluation through oral examinations, written tests, and practical application. Progress is monitored continuously with feedback from instructors.'
                    },
                    {
                        'q': 'What is the duration of each program?',
                        'a': "Integrated Sharee'a is a multi-year program with progressive levels. Thahfeel-ul-Qu'ran typically takes 3-4 years depending on individual pace and memorization capacity."
                    },
                    {
                        'q': 'Are there any fees for the programs?',
                        'a': 'The academy operates on a donation-based system. There are no fixed fees, but families are encouraged to contribute according to their capacity to support the institution.'
                    }
                ]
            }
        )
        
        if created:
            self.create_shareea_fields(shareea)
            self.stdout.write(f'  ✓ Created program: {shareea.name}')
        else:
            # Update existing program with new fields
            shareea.subtitle = "Da'wa Dars Program"
            shareea.features = [
                {'icon': 'book', 'title': 'Classical Text Study', 'description': 'In-depth study of core classical Islamic texts'},
                {'icon': 'structure', 'title': 'Mukhtasar-Based Curriculum', 'description': 'Structured curriculum following traditional methodology'},
                {'icon': 'guidance', 'title': 'Guided Learning', 'description': 'Personal guidance under experienced Ustads'},
                {'icon': 'community', 'title': 'Scholarly Environment', 'description': 'Immersive learning environment'}
            ]
            shareea.curriculum = ['Fiqh', 'Aqeedah', 'Seerah', 'Hadith Studies', 'Arabic Language', 'Usul al-Fiqh']
            shareea.outcomes = ['Strong foundational knowledge', 'Ability to understand classical texts', 'Critical thinking skills']
            shareea.faq = [
                {'q': 'Who can apply?', 'a': 'Students committed to disciplined Islamic study.'},
                {'q': 'What is the medium of instruction?', 'a': 'Arabic with English/Malayalam explanation.'}
            ]
            shareea.save()
            self.stdout.write(f'  ✓ Updated program: {shareea.name}')

        # Thahfīẓ-ul-Qu'an Program
        thahfeez, created = Program.objects.get_or_create(
            slug='thahfeez',
            defaults={
                'name': "Thahfīẓ-ul-Qu'an",
                'subtitle': "Thahfeel-ul-Qu'ran Program",
                'description': "A focused Hifz program dedicated to Qur'an memorization with accuracy, discipline, and consistent revision. The program supports students through structured routines and guided supervision to achieve complete memorization.",
                'min_age': 9,
                'max_age': 18,
                'is_active': True,
                'display_order': 2,
                'config': {
                    'duration': '3-5 years',
                    'qualification': 'Hifz Certificate',
                },
                'features': [
                    {
                        'icon': 'memorization',
                        'title': 'Systematic Memorization',
                        'description': "Structured approach to Qur'an memorization with personalized pacing"
                    },
                    {
                        'icon': 'tajweed',
                        'title': 'Tajweed Mastery',
                        'description': 'Strong emphasis on accurate pronunciation and application of tajweed rules'
                    },
                    {
                        'icon': 'revision',
                        'title': 'Daily Revision',
                        'description': 'Consistent revision schedule for strong retention'
                    },
                    {
                        'icon': 'discipline',
                        'title': 'Disciplined Environment',
                        'description': 'Structured daily routine fostering discipline and focus'
                    }
                ],
                'curriculum': [
                    'Complete Qur-an Memorization (Hifz)',
                    'Tajweed Rules and Application',
                    'Qur-anic Recitation (Tilawah)',
                    'Memorization Techniques',
                    'Revision and Retention Methods',
                    'Spiritual Development'
                ],
                'outcomes': [
                    'Complete memorization of the Holy Qur-an',
                    'Mastery of tajweed rules and proper recitation',
                    'Strong retention through systematic revision',
                    'Disciplined study habits and time management',
                    'Spiritual connection with the Qur-an'
                ],
                'gallery': [],
                'faq': [
                    {
                        'q': 'Who can apply for these programs?',
                        'a': 'Students who are committed to disciplined Islamic study and have completed basic Islamic education. Both programs welcome sincere learners dedicated to gaining authentic knowledge.'
                    },
                    {
                        'q': 'What is the medium of instruction?',
                        'a': 'Primary instruction is in Arabic with guided explanation in English/Malayalam to ensure proper understanding of concepts and texts.'
                    },
                    {
                        'q': 'How are students assessed?',
                        'a': 'Regular evaluation through oral examinations, written tests, and practical application. Progress is monitored continuously with feedback from instructors.'
                    },
                    {
                        'q': 'What is the duration of each program?',
                        'a': "Integrated Sharee'a is a multi-year program with progressive levels. Thahfeel-ul-Qu'ran typically takes 3-4 years depending on individual pace and memorization capacity."
                    },
                    {
                        'q': 'Are there any fees for the programs?',
                        'a': 'The academy operates on a donation-based system. There are no fixed fees, but families are encouraged to contribute according to their capacity to support the institution.'
                    }
                ]
            }
        )
        
        if created:
            self.create_thahfeez_fields(thahfeez)
            self.stdout.write(f'  ✓ Created program: {thahfeez.name}')
        else:
            # Update existing program with new fields
            thahfeez.subtitle = "Thahfeel-ul-Qu'ran Program"
            thahfeez.features = [
                {'icon': 'memorization', 'title': 'Systematic Memorization', 'description': 'Structured approach to Hifz'},
                {'icon': 'tajweed', 'title': 'Tajweed Mastery', 'description': 'Emphasis on proper pronunciation'},
                {'icon': 'revision', 'title': 'Daily Revision', 'description': 'Consistent revision schedule'},
                {'icon': 'discipline', 'title': 'Disciplined Environment', 'description': 'Structured daily routine'}
            ]
            thahfeez.curriculum = ['Complete Hifz', 'Tajweed Rules', 'Tilawah', 'Memorization Techniques', 'Revision Methods']
            thahfeez.outcomes = ['Complete memorization', 'Tajweed mastery', 'Retention', 'Disciplined habits']
            thahfeez.faq = [
                {'q': 'Who can apply?', 'a': 'Students committed to disciplined Islamic study.'},
                {'q': 'What is the medium of instruction?', 'a': 'Arabic with English/Malayalam explanation.'}
            ]
            thahfeez.save()
            self.stdout.write(f'  ✓ Updated program: {thahfeez.name}')

    def create_shareea_fields(self, program):
        """Create form fields for Sharee'a program"""
        fields = [
            # Step 1: Personal
            (1, 'student_photo', 'Student Photo', 'file', 'required'),
            (1, 'name', 'Full Name', 'text', 'required'),
            (1, 'dob', 'Date of Birth', 'date', 'required'),
            (1, 'phone', 'Phone Number', 'phone', 'required'),
            (1, 'email', 'Email Address', 'email', 'required'),
            (1, 'address_house_name', 'House Name', 'text', 'required'),
            (1, 'address_place', 'Place', 'text', 'required'),
            (1, 'address_post_office', 'Post Office', 'text', 'required'),
            (1, 'address_pin_code', 'PIN Code', 'text', 'required'),
            (1, 'address_state', 'State', 'text', 'required'),
            (1, 'address_district', 'District', 'text', 'required'),
            
            # Step 2: Academic
            (2, 'school_college', 'School/College Name', 'text', 'required'),
            (2, 'standard', 'Current Class', 'text', 'required'),
            (2, 'madrassa_name', 'Madrassa/Dars Currently Attending', 'text', 'optional'),
            (2, 'arabic_fluent', 'Are you fluent in Arabic?', 'checkbox', 'required'),
            (2, 'previous_quran', 'How much Quran have you memorized?', 'select', 'required'),
            (2, 'languages_known', 'Languages Known', 'multiselect', 'required'),
            (2, 'previous_institution', 'Previous Islamic Institution (if any)', 'textarea', 'optional'),
            
            # Step 3: Guardian
            (3, 'guardian_name', 'Guardian Name', 'text', 'required'),
            (3, 'guardian_relation', 'Relationship', 'select', 'required'),
            (3, 'guardian_phone', 'Guardian Phone', 'phone', 'required'),
            (3, 'guardian_email', 'Guardian Email', 'email', 'optional'),
            (3, 'guardian_occupation', 'Guardian Occupation', 'text', 'optional'),
        ]
        
        self.save_fields(program, fields)

    def create_thahfeez_fields(self, program):
        """Create form fields for Thahfīẓ program"""
        fields = [
            # Step 1: Personal
            (1, 'student_photo', 'Student Photo', 'file', 'required'),
            (1, 'name', 'Full Name', 'text', 'required'),
            (1, 'dob', 'Date of Birth', 'date', 'required'),
            (1, 'phone', 'Phone Number', 'phone', 'required'),
            (1, 'email', 'Email Address', 'email', 'required'),
            (1, 'address_house_name', 'House Name', 'text', 'required'),
            (1, 'address_place', 'Place', 'text', 'required'),
            (1, 'address_post_office', 'Post Office', 'text', 'required'),
            (1, 'address_pin_code', 'PIN Code', 'text', 'required'),
            (1, 'address_state', 'State', 'text', 'required'),
            (1, 'address_district', 'District', 'text', 'required'),
            
            # Step 2: Academic (Thahfīẓ specific)
            (2, 'madrassa_name', 'Current Madrassa', 'text', 'required'),
            (2, 'hifz_started', 'When did you start Hifz?', 'date', 'required'),
            (2, 'parts_memorized', 'Parts of Quran Memorized', 'number', 'required'),
            (2, 'tajweed_known', 'Do you know Tajweed rules?', 'checkbox', 'required'),
            (2, 'recitation_ability', 'Current Recitation Ability', 'select', 'required'),
            (2, 'memorization_speed', 'Approximate memorization speed (pages/month)', 'number', 'optional'),
            (2, 'has_mishap', 'Have you had any memorization gaps?', 'checkbox', 'optional'),
            (2, 'languages_known', 'Languages Known', 'multiselect', 'required'),
            
            # Step 3: Guardian
            (3, 'guardian_name', 'Guardian Name', 'text', 'required'),
            (3, 'guardian_relation', 'Relationship', 'select', 'required'),
            (3, 'guardian_phone', 'Guardian Phone', 'phone', 'required'),
            (3, 'guardian_email', 'Guardian Email', 'email', 'optional'),
            (3, 'guardian_occupation', 'Guardian Occupation', 'text', 'optional'),
            (3, 'supporting_hifz', 'Will you support the student\'s Hifz journey?', 'checkbox', 'required'),
        ]
        
        self.save_fields(program, fields)

    def save_fields(self, program, field_defs):
        field_type_map = {
            'text': 'text',
            'textarea': 'textarea',
            'date': 'date',
            'phone': 'phone',
            'email': 'email',
            'number': 'number',
            'file': 'file',
            'checkbox': 'checkbox',
            'select': 'select',
            'multiselect': 'multiselect',
        }
        
        choices_map = {
            'Relationship': ['Father', 'Mother', 'Brother', 'Sister', 'Uncle', 'Aunt', 'Other'],
            'Current Recitation Ability': ['Beginner', 'Intermediate', 'Advanced', 'Expert'],
            'How much Quran have you memorized?': ['None', '1-5 parts', '5-10 parts', '10-15 parts', '15+ parts'],
            'Languages Known': ['Arabic', 'English', 'Malayalam', 'Hindi', 'Urdu', 'Tamil', 'Other'],
        }
        
        for order, key, label, ftype, required in field_defs:
            required_map = {'required': 'required', 'optional': 'optional', 'conditional': 'conditional'}
            
            choices = choices_map.get(label, [])
            if ftype not in ['select', 'multiselect']:
                choices = []
            
            ProgramField.objects.get_or_create(
                program=program,
                field_key=key,
                defaults={
                    'step': order,
                    'label': label,
                    'field_type': field_type_map.get(ftype, 'text'),
                    'placeholder': f'Enter {label.lower()}',
                    'required': required_map.get(required, 'optional'),
                    'choices': choices,
                    'display_order': order,
                    'is_visible': True
                }
            )

    def create_content_pages(self):
        self.stdout.write('Creating Content Pages...')
        
        pages = [
            {
                'slug': 'about',
                'title': 'About Zainussunna Academy',
                'is_published': True,
                'content_blocks': [
                    {'type': 'text', 'order': 1, 'data': {'content': '<h1>About Us</h1><p>Zainussunna Academy is a premier Islamic educational institution dedicated to nurturing future scholars and leaders through comprehensive Islamic and modern education.</p>'}},
                    {'type': 'text', 'order': 2, 'data': {'content': '<h2>Our Mission</h2><p>To produce pious, knowledgeable, and responsible individuals who can serve humanity with Islamic values and modern expertise.</p>'}},
                ]
            },
            {
                'slug': 'programs',
                'title': 'Our Programs',
                'is_published': True,
                'content_blocks': [
                    {'type': 'text', 'order': 1, 'data': {'content': '<h1>Academic Programs</h1><p>We offer comprehensive Islamic education programs designed to cater to students of various age groups and educational backgrounds.</p>'}},
                ]
            },
            {
                'slug': 'contact',
                'title': 'Contact Us',
                'is_published': True,
                'content_blocks': [
                    {'type': 'text', 'order': 1, 'data': {'content': '<h1>Get in Touch</h1><p>We are here to answer any questions you may have.</p>'}},
                ]
            },
        ]
        
        for page_data in pages:
            page, created = ContentPage.objects.get_or_create(
                slug=page_data['slug'],
                defaults=page_data
            )
            status = 'Created' if created else 'Exists'
            self.stdout.write(f'  ✓ {status}: {page_data["title"]}')

    def create_achievements(self):
        self.stdout.write('Creating Sample Achievements...')
        
        achievements = [
            {
                'title': 'National Quran Competition Winner 🏆',
                'description': 'Our student Ahmed Khan secured First Place in the National Quran Recitation Competition 2023 held in Delhi. This achievement reflects our commitment to excellence in Tajweed and recitation.',
                'date': '2023-12-15',
                'category': 'competition',
                'is_visible': True,
                'display_order': 1
            },
            {
                'title': 'Islamic Scholarship Award 📜',
                'description': 'Recognized for excellence in Islamic Studies at the State Level. Our students have consistently demonstrated outstanding knowledge in Fiqh, Aqeedah, and Hadith.',
                'date': '2023-11-20',
                'category': 'academic',
                'is_visible': True,
                'display_order': 2
            },
            {
                'title': '50 Huffaz Complete Hifz 🎉',
                'description': 'Alhamdhulillah, congratulations to our 50 students who completed memorization of the Holy Quran with proper Tajweed. May Allah accept their efforts.',
                'date': '2023-10-15',
                'category': 'hifz',
                'is_visible': True,
                'display_order': 3
            },
            {
                'title': 'State Level Declamation Contest',
                'description': 'Our students won multiple awards in the Islamic Knowledge Declamation Contest organized by the State Islamic Education Board.',
                'date': '2023-09-10',
                'category': 'competition',
                'is_visible': True,
                'display_order': 4
            },
            {
                'title': 'Best Islamic School Award 🏅',
                'description': 'Zainussunna Academy received the "Best Islamic Educational Institution" award for our comprehensive curriculum and academic excellence.',
                'date': '2023-08-05',
                'category': 'academic',
                'is_visible': True,
                'display_order': 5
            },
            {
                'title': '100% Pass in Hifz Finals',
                'description': 'All our Hifz students passed their final memorization review with distinction. A testament to our rigorous revision system.',
                'date': '2023-07-20',
                'category': 'hifz',
                'is_visible': True,
                'display_order': 6
            },
            {
                'title': 'Arabic Language Proficiency',
                'description': 'Students achieved highest scores in Arabic Language examination conducted by the Arabic Language Authority.',
                'date': '2023-06-15',
                'category': 'academic',
                'is_visible': True,
                'display_order': 7
            },
            {
                'title': 'Community Service Recognition',
                'description': 'Our students received recognition for their voluntary community service during Ramadan, serving meals to over 500 families.',
                'date': '2023-05-01',
                'category': 'competition',
                'is_visible': True,
                'display_order': 8
            },
        ]
        
        for ach_data in achievements:
            ach, created = Achievement.objects.get_or_create(
                title=ach_data['title'],
                defaults=ach_data
            )
            status = 'Created' if created else 'Exists'
            self.stdout.write(f'  ✓ {status}: {ach_data["title"]}')

    def create_gallery(self):
        self.stdout.write('Creating Sample Gallery Items...')
        
        gallery_items = [
            {
                'title': 'Classroom Session',
                'caption': 'Students engaged in classical text study',
                'category': 'classroom',
                'is_visible': True,
                'display_order': 1
            },
            {
                'title': 'Campus Building',
                'caption': 'Main building of Zainussunna Academy',
                'category': 'campus',
                'is_visible': True,
                'display_order': 2
            },
            {
                'title': 'Annual Event 2024',
                'caption': 'Annual gathering of students and parents',
                'category': 'events',
                'is_visible': True,
                'display_order': 3
            },
            {
                'title': 'Graduation Ceremony',
                'caption': 'Celebrating our graduates',
                'category': 'graduation',
                'is_visible': True,
                'display_order': 4
            },
        ]
        
        for item_data in gallery_items:
            item, created = GalleryItem.objects.get_or_create(
                title=item_data['title'],
                defaults=item_data
            )
            status = 'Created' if created else 'Exists'
            self.stdout.write(f'  ✓ {status}: {item_data["title"]}')
    
    def create_whatsapp_config(self):
        self.stdout.write('Creating WhatsApp Configuration...')
        
        # Create default WhatsApp config if none exists
        if not WhatsAppConfig.objects.exists():
            WhatsAppConfig.objects.create(
                phone_number='++919188441614',
                is_active=True,
                admission_message_template="*New Admission Application*\n\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "*Application Details:*\n"
                    "- Name: *{student_name}*\n"
                    "- Program: {program_name}\n"
                    "- Class: {standard}\n"
                    "- Phone: {phone}\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "*Guardian Info:*\n"
                    "- Name: {guardian_name}\n"
                    "- Relation: {guardian_relation}\n"
                    "- Phone: {guardian_phone}\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "*Zainussunna Academy*\n"
                    "Excellence in Islamic Education",
                success_message_template="*Admission Submitted Successfully!*\n\n"
                    "*Zainussunna Academy*\n\n"
                    "Dear {student_name},\n\n"
                    "Your application for *{program_name}* has been submitted successfully!\n\n"
                    "*Application Number:* {application_number}\n\n"
                    "Our team will contact you shortly. Please keep your phone number ready.\n\n"
                    "*JazakAllah Khair* for choosing Zainussunna Academy!",
                notify_on_submission=True,
                send_confirmation=True
            )
            self.stdout.write('  ✓ Created WhatsApp configuration')
        else:
            self.stdout.write('  ✓ WhatsApp configuration already exists')
        
        # Create Faculty Members
        self.create_faculty()
        
        # Create Legal Pages
        self.create_legal_pages()
    
    def create_faculty(self):
        self.stdout.write('Creating Faculty Members...')
        
        faculty_members = [
            {
                'name': 'Zabair Sa-adi Al-Arshadi',
                'role': 'Director',
                'qualification': 'M.A. Islamic Studies, Al-Azhar University',
                'bio': 'A renowned scholar with over 20 years of experience in Islamic education. Dedicated to preserving classical Islamic scholarship.',
                'display_order': 1
            },
            {
                'name': 'Shihab Rahmani',
                'role': 'Asst. Instructor - Integrated Shareea',
                'qualification': 'Diploma in Islamic Theology',
                'bio': 'Specializes in teaching Fiqh and Aqeedah with a focus on classical texts.',
                'display_order': 2
            },
            {
                'name': 'Hafiz Abdul Nasar Latheefi',
                'role': 'Lead Instructor - Quranic Studies',
                'qualification': 'Hifz-ul-Quran, Tajweed Certification',
                'bio': 'An experienced Huffaz with expertise in Quran memorization and Tajweed.',
                'display_order': 3
            },
            {
                'name': 'Muhammad Ali K',
                'role': 'Arabic Language Instructor',
                'qualification': 'M.A. Arabic, University of Calicut',
                'bio': 'Fluent in Arabic with expertise in classical Arabic grammar and literature.',
                'display_order': 4
            },
            {
                'name': 'Dr. Fatima Beevi',
                'role': 'Islamic History Instructor',
                'qualification': 'Ph.D. in Islamic History',
                'bio': 'Specializes in Seerah and Islamic History with research publications.',
                'display_order': 5
            },
            {
                'name': 'Ahmad bin Abdulaziz',
                'role': 'Hadith Studies Instructor',
                'qualification': 'Shahadat al-Aalamiyah in Hadith',
                'bio': 'Memorized multiple books of Hadith and specializes in Narrations.',
                'display_order': 6
            },
        ]
        
        for faculty_data in faculty_members:
            faculty, created = Faculty.objects.get_or_create(
                name=faculty_data['name'],
                defaults={
                    'role': faculty_data['role'],
                    'qualification': faculty_data['qualification'],
                    'bio': faculty_data['bio'],
                    'display_order': faculty_data['display_order'],
                    'status': 'active'
                }
            )
            status = 'Created' if created else 'Exists'
            self.stdout.write(f'  ✓ {status}: {faculty_data["name"]}')
    
    def create_legal_pages(self):
        self.stdout.write('Creating Legal Pages...')
        
        legal_pages = [
            {
                'slug': 'privacy-policy',
                'title': 'Privacy Policy',
                'is_published': True,
                'content_blocks': [
                    {'type': 'text', 'order': 1, 'data': {'content': '<h1>Privacy Policy</h1><p>At Zainussunna Academy, we are committed to protecting your privacy and ensuring the security of your personal information.</p><h2>Information We Collect</h2><p>We collect personal information that you provide to us, including but not limited to:</p><ul><li>Name and contact information</li><li>Educational background</li><li>Guardian/parent details</li><li>Application materials</li></ul><h2>How We Use Your Information</h2><p>The information collected is used solely for:</p><ul><li>Processing admission applications</li><li>Communicating with students and guardians</li><li>Maintaining academic records</li><li>Improving our services</li></ul><h2>Data Protection</h2><p>We implement appropriate security measures to protect your personal information against unauthorized access, alteration, disclosure, or destruction.</p><h2>Contact Us</h2><p>If you have any questions about this Privacy Policy, please contact us.</p>'}}
                ]
            },
            {
                'slug': 'terms-conditions',
                'title': 'Terms & Conditions',
                'is_published': True,
                'content_blocks': [
                    {'type': 'text', 'order': 1, 'data': {'content': '<h1>Terms & Conditions</h1><p>Welcome to Zainussunna Academy. By accessing our website and services, you agree to be bound by these terms and conditions.</p><h2>Admission Terms</h2><ul><li>All admissions are subject to verification of documents</li><li>The academy reserves the right to reject applications</li><li>Students must adhere to the academy code of conduct</li><li>Regular attendance is mandatory</li></ul><h2>Academic Policies</h2><ul><li>Students must maintain academic integrity</li><li>Disciplinary actions may be taken for violations</li><li>Progress reports will be shared with guardians</li></ul><h2>Payment Terms</h2><p>The academy operates on a donation-based system. Contributions are voluntary but appreciated to support our mission.</p><h2>Modification of Terms</h2><p>We reserve the right to modify these terms at any time. Continued use of our services constitutes acceptance of any changes.</p>'}}
                ]
            },
            {
                'slug': 'refund-policy',
                'title': 'Refund Policy',
                'is_published': True,
                'content_blocks': [
                    {'type': 'text', 'order': 1, 'data': {'content': '<h1>Refund Policy</h1><p>At Zainussunna Academy, we strive to maintain transparency in all financial matters.</p><h2>Donation-Based System</h2><p>Our academy operates on a donation-based system. All contributions are voluntary and used to support the educational mission of the academy.</p><h2>No Fee Refunds</h2><p>Since we do not charge fixed fees for education, there are no fee refunds applicable.</p><h2>Donation Requests</h2><p>If you have made a donation and wish to request a refund, please contact us within 7 days of the transaction. Refunds will be processed at the academy discretion.</p><h2>Contact</h2><p>For donation refund requests, please contact the administration office.</p>'}}
                ]
            },
            {
                'slug': 'shipping-policy',
                'title': 'Shipping Policy',
                'is_published': True,
                'content_blocks': [
                    {'type': 'text', 'order': 1, 'data': {'content': '<h1>Shipping Policy</h1><p>Zainussunna Academy is an offline educational institution.</p><h2>Physical Location</h2><p>All our programs are conducted at our campus location. We do not ship any physical products.</p><h2>Online Resources</h2><p>Some educational materials may be shared digitally through our learning management system. These are provided at no additional cost to enrolled students.</p><h2>No Physical Shipping</h2><p>Please note that we do not offer shipping of any physical goods, certificates, or documents. All certificates and documents are distributed in person at the campus.</p><h2>Contact</h2><p>For any queries regarding our programs, please contact us directly.</p>'}}
                ]
            },
        ]
        
        for page_data in legal_pages:
            page, created = ContentPage.objects.get_or_create(
                slug=page_data['slug'],
                defaults=page_data
            )
            status = 'Created' if created else 'Exists'
            self.stdout.write(f'  ✓ {status}: {page_data["title"]}')

