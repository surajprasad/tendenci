from django.db.models import Q
from django.contrib import admin
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.contrib.admin import SimpleListFilter
from django.conf.urls import patterns, url
from django.template.defaultfilters import slugify
from django.utils.encoding import iri_to_uri
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.utils.translation import ugettext_lazy as _
from django.utils.encoding import force_unicode

from tendenci.apps.base.http import Http403
from tendenci.apps.memberships.forms import MembershipTypeForm
from tendenci.apps.user_groups.models import Group
from tendenci.apps.base.utils import tcurrency
from tendenci.apps.perms.admin import TendenciBaseModelAdmin
from tendenci.apps.memberships.models import (
    MembershipDefault, MembershipType, Notice,
    MembershipAppField, MembershipApp)
from tendenci.apps.memberships.forms import (
    MembershipDefaultForm, NoticeForm,
    MembershipAppForm, MembershipAppFieldAdminForm)
from tendenci.apps.memberships.utils import get_selected_demographic_field_names
from tendenci.apps.memberships.middleware import ExceededMaxTypes
from tendenci.apps.site_settings.utils import get_setting
from tendenci.apps.perms.utils import has_perm


class MembershipStatusDetailFilter(SimpleListFilter):
    title = 'status detail'
    parameter_name = 'status_detail'

    def lookups(self, request, model_admin):
        memberships = model_admin.model.objects.exclude(status_detail='archive')
        status_detail_list = set([m.status_detail for m in memberships])
        return zip(status_detail_list, status_detail_list)

    def queryset(self, request, queryset):

        if not self.value() == 'archive':
            queryset = queryset.exclude(status_detail='archive')

        if self.value():
            return queryset.filter(status_detail=self.value())
        else:
            return queryset
        
class MembershipAutoRenewFilter(SimpleListFilter):
    title = 'auto renew'
    parameter_name = 'auto_renew'
 
    def lookups(self, request, model_admin):
        return (
            (1, 'Yes'),
            (0, 'No'),
        )
 
    def queryset(self, request, queryset):
        try:
            value = int(self.value())
        except:
            value = None
        
        if value == None:
            return queryset
        
        if value == 1:
            return queryset.filter(auto_renew=True)
        
        return queryset.filter(Q(auto_renew=False) | Q(auto_renew__isnull=True))


def approve_selected(modeladmin, request, queryset):
    """
    Approves selected memberships.
    Exclude active, expired, and archived memberships.

    Sends email to member, member and global recipients.
    """

    qs_active = Q(status_detail='active')
    qs_expired = Q(status_detail='expired')
    qs_archived = Q(status_detail='archive')

    # exclude already approved memberships
    memberships = queryset.exclude(
        status=True,
        application_approved_dt__isnull=False,
    ).exclude(qs_active | qs_expired | qs_archived)

    for membership in memberships:
        is_renewal = membership.is_renewal()
        membership.approve(request_user=request.user)
        membership.send_email(request, ('approve_renewal' if is_renewal else 'approve'))
        if membership.corporate_membership_id:
            # notify corp reps
            membership.email_corp_reps(request)

approve_selected.short_description = u'Approve selected'


def renew_selected(modeladmin, request, queryset):
    """
    Renew selected memberships.
    Exclude archived memberships
    """

    qs_archived = Q(status_detail='archive')

    memberships = queryset.exclude(qs_archived)

    for membership in memberships:
        membership.renew(request_user=request.user)
        membership.send_email(request, 'renewal')

    member_names = [m.user.profile.get_name() for m in memberships]
    msg_string = 'Successfully renewed: %s' % u', '.join(member_names)
    messages.add_message(request, messages.SUCCESS, _(msg_string))

renew_selected.short_description = u'Renew selected'


def disapprove_selected(modeladmin, request, queryset):
    """
    Disapprove [only pending and active]
    selected memberships.
    """

    qs_pending = Q(status_detail='pending')
    qs_active = Q(status_detail='active')

    memberships = queryset.filter(qs_pending, qs_active)

    for membership in memberships:
        is_renewal = membership.is_renewal()
        membership.disapprove(request_user=request.user)
        membership.send_email(request, ('disapprove_renewal' if is_renewal else 'disapprove'))

disapprove_selected.short_description = u'Disapprove selected'


def expire_selected(modeladmin, request, queryset):
    """
    Expire [only active] selected memberships.
    """

    memberships = queryset.filter(
        status=True,
        status_detail='active',
        application_approved=True,
    )

    for membership in memberships:
        # Since we're selecting memberships with 'active' status_detail,
        # this `membership` is either active membership or expired
        # but not being marked as expired yet (maybe due to a failed cron job).
        membership.expire(request_user=request.user)

expire_selected.short_description = u'Expire selected'


class MembershipDefaultAdmin(admin.ModelAdmin):
    """
    MembershipDefault model
    """

    form = MembershipDefaultForm

    profile = (
        _('Profile'),
        {'fields': (
            ('first_name', 'last_name'),
            ('email', 'email2'),
            ('company', 'department'), ('position_title',),
            ('address', 'address2'), ('address_type',),
            ('city', 'state'), ('zipcode', 'country'),
            ('phone', 'phone2'),
            ('work_phone', 'home_phone'), ('mobile_phone',),
            ('fax'),
            ('url', 'url2'),
            ('dob', 'sex'), ('spouse',),
            ('hide_in_search', 'hide_address'), ('hide_email', 'hide_phone'),
            ('address_2', 'address2_2'),
            ('city_2', 'state_2'), ('zipcode_2', 'country_2'),
        )}
    )

    membership = (
        _('Membership'),
        {'fields': (
            'member_number',
            'renewal',
            'certifications',
            'work_experience',
            'referral_source',
            'referral_source_other',
            'referral_source_member_name',
            'referral_source_member_number',
            'affiliation_member_number',
            'primary_practice',
            'how_long_in_practice',
            'notes',
            'admin_notes',
            'newsletter_type',
            'directory_type',
            'chapter',
            'areas_of_expertise',
            'corporate_membership_id',
            'home_state',
            'year_left_native_country',
            'network_sectors',
            'networking',
            'government_worker',
            'government_agency',
            'license_number',
            'license_state',
            'region',
            'industry',
            'company_size',
            'promotion_code',
            'app',
        )}
    )

    education = (
        _('Education History'),
        {'fields': (
            ('school1', 'major1'), ('degree1', 'graduation_dt1'),
            ('school2', 'major2'), ('degree2', 'graduation_dt2'),
            ('school3', 'major3'), ('degree3', 'graduation_dt3'),
            ('school4', 'major4'), ('degree4', 'graduation_dt4'),
        )}
    )

    money = (
        _('Money'),
        {'fields': (
            'payment_method',
            'membership_type',
        )}
    )

    extra = (
        _('Extra'),
        {'fields': (
            'industry',
            'region',
        )}
    )

    status = (
        _('Status'),
        {'fields': (
            'join_dt',
            'renew_dt',
            'expire_dt',
        )}
    )

    fieldsets = (
        profile,
        membership,
        education,
        money,
        status
    )

    search_fields = [
        'user__first_name',
        'user__last_name',
        'user__email',
        'member_number',
        'user__username'
    ]

    list_display = [
        'id',
        'name',
        'email',
        'member_number',
        'membership_type_link',
        'get_approve_dt',
        'get_expire_dt',
        'get_status',
        'get_invoice',
    ]
    if get_setting('module', 'recurring_payments', 'enabled') and get_setting('module', 'memberships', 'autorenew'):
        list_display.append('auto_renew')
    list_display_links = ('name',)

    list_filter = [
        MembershipStatusDetailFilter,
        'membership_type',
    ]
    if get_setting('module', 'recurring_payments', 'enabled') and get_setting('module', 'memberships', 'autorenew'):
        list_filter.append(MembershipAutoRenewFilter)

    actions = [
        approve_selected,
        renew_selected,
        disapprove_selected,
        expire_selected,
    ]

    def get_fieldsets(self, request, instance=None):
        demographics_fields = get_selected_demographic_field_names(
            instance and instance.app)

        if demographics_fields:
            demographics = (
                    _('Demographics'),
                    {'fields': tuple(demographics_fields)
                     }
                           )
        fieldsets = (
                self.profile,
                self.membership,
                self.education,)
        if demographics_fields:
            fieldsets += (
                demographics,
            )
        fieldsets += (
                self.money,
                self.status)

        return fieldsets

    def name(self, instance):
        name = '%s %s' % (
            instance.user.first_name,
            instance.user.last_name,
        )
        name.strip()
        return name
    name.admin_order_field = 'user__last_name'

    def email(self, instance):
        return instance.user.email
    email.admin_order_field = 'user__email'

    def get_status(self, instance):
        return instance.get_status().capitalize()
    get_status.short_description = u'Status'
    get_status.admin_order_field = 'status_detail'

    def get_invoice(self, instance):
        inv = instance.get_invoice()
        if inv:
            if inv.balance > 0:
                return '<a href="%s" title="Invoice">#%s (%s)</a>' % (
                    inv.get_absolute_url(),
                    inv.pk,
                    tcurrency(inv.balance)
                )
            else:
                return '<a href="%s" title="Invoice">#%s</a>' % (
                    inv.get_absolute_url(),
                    inv.pk
                )
        return ""
    get_invoice.short_description = u'Invoice'
    get_invoice.allow_tags = True

    def get_create_dt(self, instance):
        return instance.create_dt.strftime('%b %d, %Y, %I:%M %p')
    get_create_dt.short_description = u'Created On'

    def get_approve_dt(self, instance):
        dt = instance.application_approved_dt

        if dt:
            return dt.strftime('%b %d, %Y, %I:%M %p')
        return u''
    get_approve_dt.short_description = u'Approved On'
    get_approve_dt.admin_order_field = 'application_approved_dt'

    def get_expire_dt(self, instance):
        dt = instance.expire_dt

        if dt:
            return dt.strftime('%m/%d/%Y')
        return u''
    get_expire_dt.short_description = u'Expire Date'

    def get_actions(self, request):
        actions = super(MembershipDefaultAdmin, self).get_actions(request)
        if not has_perm(request.user, 'memberships.approve_membershipdefault'):
            del actions['approve_selected']
        return actions

    def save_form(self, request, form, change):
        """
        Save membership [+ more] model
        """
        return form.save(request=request, commit=False)

    def add_view(self, request, form_url='', extra_context=None):
        """
        Intercept add page and redirect to form.
        """
        apps = MembershipApp.objects.filter(
            status=True,
            status_detail__in=['published', 'active'])

        count = apps.count()
        if count == 1:
            app = apps[0]
            if app.use_for_corp:
                return HttpResponseRedirect(
                    reverse('membership_default.corp_pre_add')
                )
            else:
                return HttpResponseRedirect(
                    reverse('membership_default.add', args=[app.slug])
                )
        else:
            return HttpResponseRedirect(
                reverse('admin:memberships_membershipapp_changelist')
            )

    def response_change(self, request, obj):
        """
        When the change page is submitted we can redirect
        to a URL specified in the next parameter.
        """
        POST_KEYS = request.POST.keys()
        GET_KEYS = request.GET.keys()
        NEXT_URL = iri_to_uri('%s') % request.GET.get('next')

        do_next_url = (
            '_addanother' not in POST_KEYS,
            '_continue' not in POST_KEYS,
            'next' in GET_KEYS)

        if all(do_next_url):
            return HttpResponseRedirect(NEXT_URL)

        return super(MembershipDefaultAdmin, self).response_change(request, obj)

    def has_change_permission(self, request, obj=None):
        return (has_perm(request.user, 'memberships.approve_membershipdefault') or
                has_perm(request.user, 'memberships.change_membershipdefault'))

    def get_urls(self):
        """
        Add the export view to urls.
        """
        urls = super(MembershipDefaultAdmin, self).get_urls()

        extra_urls = patterns(
            u'',
            url("^approve/(?P<pk>\d+)/$",
                self.admin_site.admin_view(self.approve),
                name='membership.admin_approve'),
            url("^renew/(?P<pk>\d+)/$",
                self.admin_site.admin_view(self.renew),
                name='membership.admin_renew'),
            url("^disapprove/(?P<pk>\d+)/$",
                self.admin_site.admin_view(self.disapprove),
                name='membership.admin_disapprove'),
            url("^expire/(?P<pk>\d+)/$",
                self.admin_site.admin_view(self.expire),
                name='membership.admin_expire'),
        )
        return extra_urls + urls

    # django-admin custom views ----------------------------------------

    def approve(self, request, pk):
        """
        Approve membership and redirect to
        membershipdefault change page.
        """
        if not has_perm(request.user, 'memberships.approve_membershipdefault'):
            raise Http403

        m = get_object_or_404(MembershipDefault, pk=pk)
        is_renewal = m.is_renewal()
        m.approve(request_user=request.user)
        m.send_email(request, ('approve_renewal' if is_renewal else 'approve'))
        if m.corporate_membership_id:
            # notify corp reps
            m.email_corp_reps(request)

        messages.add_message(
            request,
            messages.SUCCESS,
            _('Successfully Approved')
        )

        return redirect(reverse(
            'admin:memberships_membershipdefault_change',
            args=[pk],
        ))

    def renew(self, request, pk):
        """
        Renew membership and redirect to
        membershipdefault change page.
        """
        m = get_object_or_404(MembershipDefault, pk=pk)
        m.renew(request_user=request.user)
        m.send_email(request, 'renewal')

        messages.add_message(
            request,
            messages.SUCCESS,
            _('Successfully Renewed')
        )

        return redirect(reverse(
            'admin:memberships_membershipdefault_change',
            args=[pk],
        ))

    def disapprove(self, request, pk):
        """
        Disapprove membership and redirect to
        membershipdefault change page.
        """
        m = get_object_or_404(MembershipDefault, pk=pk)
        is_renewal = m.is_renewal()
        m.disapprove(request_user=request.user)
        m.send_email(request, ('disapprove_renewal' if is_renewal else 'disapprove'))

        messages.add_message(
            request,
            messages.SUCCESS,
            _('Successfully Disapproved')
        )

        return redirect(reverse(
            'admin:memberships_membershipdefault_change',
            args=[pk],
        ))

    def expire(self, request, pk):
        """
        Expire membership and redirect to
        membershipdefault change page.
        """
        m = get_object_or_404(MembershipDefault, pk=pk)
        m.expire(request_user=request.user)

        messages.add_message(
            request,
            messages.SUCCESS,
            _('Successfully Expired')
        )

        return redirect(reverse(
            'admin:memberships_membershipdefault_change',
            args=[pk],
        ))


class MembershipAppFieldAdmin(admin.TabularInline):
    model = MembershipAppField
    fields = ('label', 'field_name', 'display', 'required', 'admin_only', 'position',)
    extra = 0
    can_delete = False
    verbose_name = _('Section Break')
    ordering = ("position",)
    template = "memberships/admin/membershipapp/tabular.html"


def clone_apps(modeladmin, request, queryset):
    for form in queryset:
        form.clone()

clone_apps.short_description = 'Clone selected forms'


class MembershipAppAdmin(admin.ModelAdmin):
    inlines = (MembershipAppFieldAdmin, )
    prepopulated_fields = {'slug': ['name']}
    list_display = ('id', 'name', 'application_form_link', 'status_detail')
    list_display_links = ('name',)
    search_fields = ('name', 'status_detail')
    fieldsets = (
        (None, {'fields': ('name', 'slug', 'description',
                           'confirmation_text', 'notes', 'allow_multiple_membership',
                           'membership_types', 'payment_methods',
                           'include_tax', 'tax_rate',
                           'use_for_corp', 'use_captcha', 'discount_eligible')},),
        (_('Donation'), {'fields': ('donation_enabled', 'donation_label', 'donation_default_amount'),
                         'description': _('If donation is enabled, a field will be added to the application\
                         to allow users to select the default amount or specify an amount to donate')}),
        (_('Permissions'), {'fields': ('allow_anonymous_view',)}),
        (_('Advanced Permissions'), {'classes': ('collapse',), 'fields': (
            'user_perms',
            'member_perms',
            'group_perms',
        )}),
        (_('Status'), {'fields': (
            'status_detail',
        )}),
    )

    form = MembershipAppForm
    change_form_template = "memberships/admin/membershipapp/change_form.html"
    actions = (clone_apps,)

    class Media:
        js = (
            '//ajax.googleapis.com/ajax/libs/jquery/2.1.1/jquery.min.js',
            '//ajax.googleapis.com/ajax/libs/jqueryui/1.11.0/jquery-ui.min.js',
            '%sjs/admin/membapp_tabular_inline_ordering.js' % settings.STATIC_URL,
            '%sjs/global/tinymce.event_handlers.js' % settings.STATIC_URL,
            '%sjs/tax_fields.js' % settings.STATIC_URL,
        )
        css = {'all': ['%scss/admin/dynamic-inlines-with-sort.css' % settings.STATIC_URL,
                       '%scss/memberships-admin.css' % settings.STATIC_URL], }


class MembershipTypeAdmin(TendenciBaseModelAdmin):
    list_display = ['name', 'price', 'admin_fee', 'show_group', 'require_approval',
                     'allow_renewal', 'renewal_price', 'renewal',
                     'admin_only', 'status_detail']
    list_filter = ['name', 'price', 'status_detail']

    exclude = ('status',)

    fieldsets = (
        (None, {'fields': ('name', 'price', 'admin_fee', 'description')}),
        (_('Expiration Method'), {'fields': ('never_expires', 'type_exp_method',)}),
        (_('Renewal Options'), {'fields': (('allow_renewal', 'renewal', 'renewal_require_approval'),
                                        'renewal_price',
                                        'renewal_period_start',
                                        'renewal_period_end',)}),

        (_('Other Options'), {'fields': (
            'expiration_grace_period', ('require_approval',
            'admin_only'), 'require_payment_approval', 'position', 'status_detail')}),
    )

    form = MembershipTypeForm
    ordering = ['position']

    def get_actions(self, request):
        actions = super(MembershipTypeAdmin, self).get_actions(request)
        return actions

    def add_view(self, request):
        num_types = MembershipType.objects.all().count()
        max_types = settings.MAX_MEMBERSHIP_TYPES
        if num_types >= max_types:
            raise ExceededMaxTypes
        return super(MembershipTypeAdmin, self).add_view(request)

    class Media:
        js = ('//ajax.googleapis.com/ajax/libs/jquery/2.1.1/jquery.min.js',
              "%sjs/membtype.js" % settings.STATIC_URL,)

    def show_group(self, instance):
        if instance.group:
            return '<a href="{0}" title="{1}">{1} (id: {2})</a>'.format(
                    reverse('group.detail', args=[instance.group.slug]),
                    instance.group,
                    instance.group.id
                )
        return ""
    show_group.short_description = u'Group'
    show_group.allow_tags = True
    show_group.admin_order_field = 'group'

    def save_model(self, request, object, form, change):
        instance = form.save(commit=False)

        # save the expiration method fields
        type_exp_method = form.cleaned_data['type_exp_method']
        type_exp_method_list = type_exp_method.split(",")
        for i, field in enumerate(form.type_exp_method_fields):
            if field == 'fixed_option2_can_rollover':
                if type_exp_method_list[i] == '':
                    type_exp_method_list[i] = ''
            else:
                if type_exp_method_list[i] == '':
                    type_exp_method_list[i] = "0"

            setattr(instance, field, type_exp_method_list[i])

        if not change:
            instance.creator = request.user
            instance.creator_username = request.user.username
            instance.owner = request.user
            instance.owner_username = request.user.username

            # create a group for this type
            group = Group()
            group.name = 'Membership: %s' % instance.name
            group.slug = slugify(group.name)
            # just in case, check if this slug already exists in group.
            # if it does, make a unique slug
            tmp_groups = Group.objects.filter(slug__istartswith=group.slug)
            if tmp_groups:
                t_list = [g.slug[len(group.slug):] for g in tmp_groups]
                num = 1
                while str(num) in t_list:
                    num += 1
                group.slug = '%s%s' % (group.slug, str(num))
                # group name is also a unique field
                group.name = '%s%s' % (group.name, str(num))

            group.label = instance.name
            group.type = 'system_generated'
            group.email_recipient = request.user.email
            group.show_as_option = 0
            group.allow_self_add = 0
            group.allow_self_remove = 0
            group.description = "Auto-generated with the membership type. Used for membership only"
            group.notes = "Auto-generated with the membership type. Used for membership only"
            #group.use_for_membership = 1
            group.creator = request.user
            group.creator_username = request.user.username
            group.owner = request.user
            group.owner_username = request.user.username

            group.save()

            instance.group = group

        # save the object
        instance.save()

        #form.save_m2m()

        return instance


class NoticeAdmin(admin.ModelAdmin):
    def notice_log(self):
        return '<a href="%s%s?notice_id=%d">View logs</a>' % (get_setting('site', 'global', 'siteurl'),
                         reverse('membership.notice.log.search'), self.id)
    notice_log.allow_tags = True

    list_display = ['id', 'notice_name', notice_log, 'content_type',
                     'membership_type', 'status', 'status_detail']
    list_display_links = ('notice_name',)
    list_filter = ['notice_type', 'status_detail']

    fieldsets = (
        (None, {'fields': ('notice_name', 'notice_time_type', 'membership_type')}),
        (_('Email Fields'), {'fields': ('subject', 'content_type', 'sender', 'sender_display', 'email_content')}),
        (_('Other Options'), {'fields': ('status', 'status_detail')}),
    )

    form = NoticeForm

    class Media:
        js = (
            '//ajax.googleapis.com/ajax/libs/jquery/2.1.1/jquery.min.js',
            '%sjs/global/tinymce.event_handlers.js' % settings.STATIC_URL,
            '%sjs/admin/membnotices.js' % settings.STATIC_URL,
        )

    def save_model(self, request, object, form, change):
        instance = form.save(commit=False)

        # save the expiration method fields
        notice_time_type = form.cleaned_data['notice_time_type']
        notice_time_type_list = notice_time_type.split(",")
        instance.num_days = notice_time_type_list[0]
        instance.notice_time = notice_time_type_list[1]
        instance.notice_type = notice_time_type_list[2]

        if not change:
            instance.creator = request.user
            instance.creator_username = request.user.username
            instance.owner = request.user
            instance.owner_username = request.user.username

        instance.save()

        return instance

    def get_urls(self):
        urls = super(NoticeAdmin, self).get_urls()
        extra_urls = patterns('',
            url("^clone/(?P<pk>\d+)/$",
                self.admin_site.admin_view(self.clone),
                name='membership_notice.admin_clone'),
        )
        return extra_urls + urls

    def clone(self, request, pk):
        """
        Make a clone of this notice.
        """
        notice = get_object_or_404(Notice, pk=pk)
        notice_clone = Notice()

        ignore_fields = ['guid', 'id', 'create_dt', 'update_dt',
                         'creator', 'creator_username',
                         'owner', 'owner_username']
        field_names = [field.name
                        for field in notice.__class__._meta.fields
                        if field.name not in ignore_fields]

        for name in field_names:
            setattr(notice_clone, name, getattr(notice, name))

        notice_clone.notice_name = 'Clone of %s' % notice_clone.notice_name
        notice_clone.creator = request.user
        notice_clone.creator_username = request.user.username
        notice_clone.owner = request.user
        notice_clone.owner_username = request.user.username
        notice_clone.save()

        return redirect(reverse(
            'admin:memberships_notice_change',
            args=[notice_clone.pk],
        ))


class AppListFilter(SimpleListFilter):
    title = _('Membership App')
    parameter_name = 'membership_app_id'

    def lookups(self, request, model_admin):
        apps_list = MembershipApp.objects.filter(
                        status=True,
                        status_detail__in=['active', 'published']
                        ).values_list('id', 'name'
                        ).order_by('id')
        return [(app_tuple[0], app_tuple[1]) for app_tuple in apps_list]

    def queryset(self, request, queryset):
        if self.value():
            queryset = queryset.filter(
                    membership_app_id=int(self.value()))
        queryset = queryset.filter(display=True)
        return queryset


class MembershipAppField2Admin(admin.ModelAdmin):
    model = MembershipAppField
    list_display = ['id', 'label', 'field_name', 'display',
              'required', 'admin_only', 'position',
              ]
    list_display_links = ('label',)

    readonly_fields = ('membership_app', 'field_name')

    list_editable = ['position']
    ordering = ("position",)
    list_filter = (AppListFilter,)
    form = MembershipAppFieldAdminForm

    class Media:
        js = (
            '//ajax.googleapis.com/ajax/libs/jquery/2.1.1/jquery.min.js',
            '//ajax.googleapis.com/ajax/libs/jqueryui/1.11.0/jquery-ui.min.js',
            '%sjs/admin/admin-list-reorder.js' % settings.STATIC_URL,
        )

    def get_fieldsets(self, request, obj=None):
        extra_fields = ['description', 'help_text',
                        'choices', 'default_value', 'css_class']
        if obj:
            if obj.field_name:
                extra_fields.remove('description')
            else:
                extra_fields.remove('help_text')
                extra_fields.remove('choices')
                extra_fields.remove('default_value')
        fields = ('membership_app', 'label', 'field_name', 'field_type',
                    'display', 'required', 'admin_only',
                             ) + tuple(extra_fields)

        return ((None, {'fields': fields
                        }),)

    def get_object(self, request, object_id, from_field=None):
        obj = super(MembershipAppField2Admin, self).get_object(request, object_id)

        # assign default field_type
        if obj:
            if not obj.field_type:
                if not obj.field_name:
                    obj.field_type = 'section_break'
                else:
                    obj.field_type = MembershipAppField.get_default_field_type(obj.field_name)

        return obj

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def get_actions(self, request):
        return None

    def response_change(self, request, obj):
        """
        If the 'Save' button is clicked, redirect to fields list
        with the selected app.
        """
        if "_save" in request.POST:
            opts = obj._meta
            verbose_name = opts.verbose_name
            module_name = opts.model_name
            if obj._deferred:
                opts_ = opts.proxy_for_model._meta
                verbose_name = opts_.verbose_name
                module_name = opts_.model_name

            msg = _('The %(name)s "%(obj)s" was changed successfully.') % {
                        'name': force_unicode(verbose_name),
                        'obj': force_unicode(obj)}
            self.message_user(request, msg)
            post_url = '%s?membership_app_id=%d' % (
                            reverse('admin:%s_%s_changelist' %
                                   (opts.app_label, module_name),
                                   current_app=self.admin_site.name),
                            obj.membership_app_id)
            return HttpResponseRedirect(post_url)
        else:
            return super(MembershipAppField2Admin, self).response_change(request, obj)


admin.site.register(MembershipDefault, MembershipDefaultAdmin)
admin.site.register(MembershipApp, MembershipAppAdmin)
admin.site.register(MembershipAppField, MembershipAppField2Admin)
admin.site.register(MembershipType, MembershipTypeAdmin)
admin.site.register(Notice, NoticeAdmin)
