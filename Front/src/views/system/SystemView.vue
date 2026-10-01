<template>
  <div class="system-page">
    <div class="panel">
      <el-tabs v-model="activeTab" class="system-tabs">
        <!-- 用户管理 -->
        <el-tab-pane label="用户管理" name="users">
          <!-- 四条件查询条（design D7） -->
          <div class="filter-bar">
            <el-input
              v-model="userFilter.username"
              placeholder="用户名"
              clearable
              class="filter-item filter-item--name"
              @keyup.enter="onUserSearch"
              @clear="onUserSearch"
            />
            <el-select v-model="userFilter.role" placeholder="角色" clearable class="filter-item filter-item--role">
              <el-option v-for="r in roles" :key="r.code" :label="r.name" :value="r.code" />
            </el-select>
            <el-select v-model="userFilter.status" placeholder="状态" clearable class="filter-item filter-item--status">
              <el-option label="启用" value="active" />
              <el-option label="禁用" value="disabled" />
            </el-select>
            <el-date-picker
              v-model="userFilter.createdRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              range-separator="至"
              start-placeholder="创建起始"
              end-placeholder="创建截止"
              class="filter-item filter-item--range"
            />
            <el-button type="primary" size="small" @click="onUserSearch">查询</el-button>
            <el-button size="small" @click="onUserReset">重置</el-button>
            <span class="spacer"></span>
            <el-button v-permission="'manage'" type="primary" size="small" :icon="Plus" @click="openUserCreate">
              新建用户
            </el-button>
          </div>

          <el-table
            v-loading="usersLoading"
            :data="users"
            stripe
            empty-text="暂无用户"
            style="width: 100%"
          >
            <el-table-column label="用户名" prop="username" width="140" class-name="mono-col" />
            <el-table-column label="昵称" prop="nickname" min-width="120" />
            <el-table-column label="角色" width="120">
              <template #default="{ row }">
                <span class="badge" :class="isAdminUserRow(row) ? 'badge--accent' : 'badge--default'">
                  {{ row.role_name }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-switch
                  v-model="row.status"
                  active-value="active"
                  inactive-value="disabled"
                  :disabled="isAdminUserRow(row)"
                  @change="(v: string) => onToggleUser(row, v as 'active' | 'disabled')"
                />
              </template>
            </el-table-column>
            <el-table-column label="创建时间" width="120">
              <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="220" align="right">
              <template #default="{ row }">
                <el-button v-permission="'manage'" link type="primary" size="small" @click="openUserEdit(row)">编辑</el-button>
                <el-button v-permission="'manage'" link type="primary" size="small" @click="onResetPwd(row)">重置密码</el-button>
                <el-button
                  v-permission="'manage'"
                  link
                  type="danger"
                  size="small"
                  :disabled="isAdminUserRow(row)"
                  @click="onDeleteUser(row)"
                >
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 角色管理 -->
        <el-tab-pane label="角色管理" name="roles">
          <!-- 角色名关键字查询条（design D7） -->
          <div class="filter-bar">
            <el-input
              v-model="roleFilterName"
              placeholder="角色名关键字"
              clearable
              class="filter-item filter-item--name"
              @keyup.enter="onRoleSearch"
              @clear="onRoleSearch"
            />
            <el-button type="primary" size="small" @click="onRoleSearch">查询</el-button>
            <el-button size="small" @click="onRoleReset">重置</el-button>
            <span class="spacer"></span>
            <el-button v-permission="'manage'" type="primary" size="small" :icon="Plus" @click="openRoleCreate">
              新建角色
            </el-button>
          </div>

          <el-table
            v-loading="rolesLoading"
            :data="filteredRoles"
            stripe
            empty-text="暂无角色"
            style="width: 100%"
          >
            <el-table-column label="角色名" prop="name" min-width="140" />
            <el-table-column label="角色代码" prop="code" width="140" class-name="mono-col" />
            <el-table-column label="描述" prop="description" min-width="200" />
            <el-table-column label="用户数" prop="user_count" width="90" align="right" class-name="mono-col" />
            <el-table-column label="是否 admin" width="130">
              <template #default="{ row }">
                <span v-if="isAdminRole(row)" class="badge badge--warning">是 · 内置</span>
                <span v-else class="badge badge--default">否</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="220" align="right">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="openRoleUsers(row)">用户</el-button>
                <el-button v-permission="'manage'" link type="primary" size="small" @click="openRoleEdit(row)">编辑</el-button>
                <el-button
                  v-permission="'manage'"
                  link
                  type="danger"
                  size="small"
                  :disabled="isAdminRole(row)"
                  @click="onDeleteRole(row)"
                >
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 权限配置 -->
        <el-tab-pane label="权限配置" name="perm">
          <div class="perm-config">
            <div class="form-row">
              <label>选择角色</label>
              <el-select v-model="permRoleCode" placeholder="选择角色" style="width: 240px" @change="onPermRoleChange">
                <el-option
                  v-for="r in roles"
                  :key="r.code"
                  :label="r.name"
                  :value="r.code"
                />
              </el-select>
            </div>

            <div v-if="permRole" class="perm-tree">
              <div class="perm-group">
                <div class="perm-node perm-node--parent">
                  <el-checkbox
                    :model-value="isAllMenu"
                    :indeterminate="isSomeMenu"
                    :disabled="isAdminRole(permRole)"
                    @change="toggleAllMenu"
                  >
                    菜单权限 <span class="perm-code mono">menu:*</span>
                  </el-checkbox>
                </div>
                <div class="perm-children">
                  <div v-for="p in menuPerms" :key="p.code" class="perm-node">
                    <el-checkbox
                      :model-value="permDraft.includes(p.code)"
                      :disabled="isAdminRole(permRole)"
                      @change="(v: boolean | string | number) => togglePerm(p.code, v)"
                    >
                      {{ p.name }} <span class="perm-code mono">{{ p.code }}</span>
                    </el-checkbox>
                  </div>
                </div>
              </div>
              <div class="perm-group">
                <div class="perm-node perm-node--parent">
                  <el-checkbox
                    :model-value="permDraft.includes('manage')"
                    :disabled="isAdminRole(permRole)"
                    @change="(v: boolean | string | number) => togglePerm('manage', v)"
                  >
                    管理权限 <span class="perm-code mono">manage</span>
                  </el-checkbox>
                </div>
              </div>

              <div class="toolbar">
                <el-button
                  v-permission="'manage'"
                  type="primary"
                  :loading="permSaving"
                  :disabled="isAdminRole(permRole)"
                  @click="onSavePerms"
                >
                  保存
                </el-button>
                <span v-if="isAdminRole(permRole)" class="text-disabled admin-hint">admin 角色拥有全部权限，不可修改</span>
              </div>
            </div>

            <EmptyState v-else description="请选择角色以配置权限" />
          </div>
        </el-tab-pane>

        <!-- LLM 供应商（design D8.1 / 6.5）：manage 权限可见与操作 -->
        <el-tab-pane v-if="canManage" label="LLM 供应商" name="llm">
          <div class="toolbar">
            <span class="text-disabled llm-hint">激活切换对后续提问即时生效，无需重启</span>
            <span class="spacer"></span>
            <el-button v-permission="'manage'" type="primary" size="small" :icon="Plus" @click="openLlmCreate">
              新增供应商
            </el-button>
          </div>

          <!-- 测试连接结果展示（{ok, detail}） -->
          <div
            v-if="llmTestResult"
            class="llm-test-result"
            :class="llmTestResult.ok ? 'is-ok' : 'is-fail'"
          >
            <el-icon><CircleCheckFilled v-if="llmTestResult.ok" /><CircleCloseFilled v-else /></el-icon>
            <span>{{ llmTestResult.detail }}</span>
            <span class="spacer"></span>
            <el-icon class="llm-test-result__close" @click="llmTestResult = null"><Close /></el-icon>
          </div>

          <el-table
            v-loading="llmLoading"
            :data="llmProviders"
            stripe
            empty-text="暂无供应商预设"
            style="width: 100%"
          >
            <el-table-column label="名称" prop="name" min-width="140" />
            <el-table-column label="接口地址" prop="base_url" min-width="220" class-name="mono-col" />
            <el-table-column label="模型" prop="model" width="150" class-name="mono-col" />
            <el-table-column label="API Key" width="130" class-name="mono-col">
              <template #default="{ row }">
                <span class="llm-key">{{ row.api_key }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <span v-if="row.active" class="badge badge--accent">使用中</span>
                <span v-else class="badge badge--default">未激活</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="220" align="right">
              <template #default="{ row }">
                <el-button
                  v-permission="'manage'"
                  link
                  type="primary"
                  size="small"
                  :disabled="row.active"
                  @click="onActivateLlm(row)"
                >
                  激活
                </el-button>
                <el-button v-permission="'manage'" link type="primary" size="small" @click="onTestLlm(row)">
                  测试连接
                </el-button>
                <el-button v-permission="'manage'" link type="danger" size="small" @click="onDeleteLlm(row)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <UserDialog v-model="userDialogVisible" :user="editingUser" :roles="roles" @saved="onUserSaved" />
    <RoleDialog v-model="roleDialogVisible" :role="editingRole" :permissions="permissions" @saved="loadRoles" />
    <LlmProviderDialog v-model="llmDialogVisible" @saved="loadLlm" />

    <!-- 重置密码对话框（管理员输入新密码，design D2 契约） -->
    <el-dialog
      v-model="pwdDialogVisible"
      :title="`重置密码 · ${pwdUser?.username || ''}`"
      width="420px"
      :close-on-click-modal="false"
      append-to-body
    >
      <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-position="top" @submit.prevent="onPwdSubmit">
        <el-form-item label="新密码" prop="password">
          <el-input
            v-model="pwdForm.password"
            type="password"
            show-password
            placeholder="输入新密码（原密码将失效）"
            @keyup.enter="onPwdSubmit"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="pwdSaving" @click="onPwdSubmit">重置</el-button>
      </template>
    </el-dialog>

    <!-- 角色-用户绑定抽屉（design D7） -->
    <el-drawer
      v-model="roleDrawerVisible"
      :title="`角色用户 · ${drawerRole?.name || ''}`"
      size="480px"
      append-to-body
    >
      <div class="role-drawer">
        <div class="drawer-section">
          <div class="drawer-section__title">成员列表 <span class="text-disabled">（{{ roleMembers.length }}）</span></div>
          <el-table v-loading="membersLoading" :data="roleMembers" size="small" stripe empty-text="暂无成员" style="width: 100%">
            <el-table-column label="用户名" prop="username" width="120" class-name="mono-col" />
            <el-table-column label="昵称" prop="nickname" min-width="100" />
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <span class="badge" :class="row.status === 'active' ? 'badge--default' : 'badge--disabled'">
                  {{ row.status === 'active' ? '启用' : '禁用' }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="drawer-section">
          <div class="drawer-section__title">待绑定用户</div>
          <div class="drawer-hint text-disabled">选中的用户将绑定到本角色（单角色模型，原角色自动解除）</div>
          <el-select
            v-model="bindUserIds"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择待绑定用户"
            style="width: 100%"
          >
            <el-option
              v-for="u in bindCandidates"
              :key="u.id"
              :label="`${u.username} · ${u.nickname}（现角色：${u.role_name}）`"
              :value="u.id"
            />
          </el-select>
          <div class="drawer-actions">
            <el-button
              v-permission="'manage'"
              type="primary"
              :loading="bindSaving"
              :disabled="bindUserIds.length === 0"
              @click="onBindUsers"
            >
              绑定
            </el-button>
            <el-button size="small" @click="loadRoleMembers">刷新</el-button>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { Plus, CircleCheckFilled, CircleCloseFilled, Close } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import EmptyState from '@/components/ui/EmptyState.vue'
import UserDialog from './UserDialog.vue'
import RoleDialog from './RoleDialog.vue'
import LlmProviderDialog from './LlmProviderDialog.vue'
import * as systemApi from '@/api/modules/system'
import { useAuthStore } from '@/stores/auth'
import type { User, Role, Permission, LlmProvider, LlmTestResult } from '@/api/types'

const activeTab = ref<'users' | 'roles' | 'perm' | 'llm'>('users')

// manage 权限：LLM 供应商入口仅管理员可见（design D8.1 / 6.5）
const auth = useAuthStore()
const canManage = computed(() => auth.hasPerm('manage'))

const users = ref<User[]>([])
const roles = ref<Role[]>([])
const permissions = ref<Permission[]>([])
const usersLoading = ref(false)
const rolesLoading = ref(false)

// --- 用户四条件查询（design D7：用户名/角色/状态/创建时间区间，AND 组合） ---
const userFilter = reactive<{
  username: string
  role: string
  status: '' | 'active' | 'disabled'
  createdRange: [string, string] | null
}>({
  username: '',
  role: '',
  status: '',
  createdRange: null,
})

async function loadUsers() {
  usersLoading.value = true
  try {
    users.value = await systemApi.getUsers({
      username: userFilter.username.trim() || undefined,
      role: userFilter.role || undefined,
      status: userFilter.status || undefined,
      created_from: userFilter.createdRange?.[0] || undefined,
      created_to: userFilter.createdRange?.[1] || undefined,
    })
  } catch {
    // 错误提示由 client 拦截器按后端 detail 展示
  } finally {
    usersLoading.value = false
  }
}

function onUserSearch() {
  loadUsers()
}

function onUserReset() {
  userFilter.username = ''
  userFilter.role = ''
  userFilter.status = ''
  userFilter.createdRange = null
  loadUsers()
}

function onUserSaved() {
  loadUsers()
  if (roleDrawerVisible.value && drawerRole.value) loadRoleMembers()
}

// --- 角色名查询（design D7） ---
// roles 为全量（供用户对话框/权限下拉/admin 判定），filteredRoles 为角色表（带 name 条件）
const roleFilterName = ref('')
const filteredRoles = ref<Role[]>([])

async function loadRoles() {
  rolesLoading.value = true
  try {
    const name = roleFilterName.value.trim() || undefined
    const [all, table] = await Promise.all([
      systemApi.getRoles(),
      systemApi.getRoles({ name }),
    ])
    roles.value = all
    filteredRoles.value = table
  } catch {
    // 错误提示由 client 拦截器按后端 detail 展示
  } finally {
    rolesLoading.value = false
  }
}

function onRoleSearch() {
  loadRoles()
}

function onRoleReset() {
  roleFilterName.value = ''
  loadRoles()
}

async function loadPermissions() {
  try {
    permissions.value = await systemApi.getPermissions()
  } catch {
    // 错误提示由 client 拦截器按后端 detail 展示
  }
}

onMounted(() => {
  loadUsers()
  loadRoles()
  loadPermissions()
  if (canManage.value) loadLlm()
})

// --- admin 保护判定（design D2：所属角色 is_admin=true 或 code=admin） ---
function isAdminRole(r: Role): boolean {
  return r.is_admin || r.code === 'admin'
}

function isAdminUserRow(u: User): boolean {
  if (u.role === 'admin') return true
  return !!roles.value.find((r) => r.code === u.role && isAdminRole(r))
}

// --- 用户操作 ---
const userDialogVisible = ref(false)
const editingUser = ref<User | null>(null)

function openUserCreate() {
  editingUser.value = null
  userDialogVisible.value = true
}
function openUserEdit(row: User) {
  editingUser.value = { ...row }
  userDialogVisible.value = true
}

async function onToggleUser(row: User, v: 'active' | 'disabled') {
  if (v === 'disabled' && isAdminUserRow(row)) {
    ElMessage.warning('admin 用户不可停用')
    row.status = 'active'
    return
  }
  try {
    await systemApi.updateUser(row.id, { status: v })
    ElMessage.success(v === 'active' ? '已启用' : '已禁用')
  } catch {
    // 失败回滚开关；错误提示由 client 拦截器按后端 detail 展示（admin 保护 403 等）
    row.status = v === 'active' ? 'disabled' : 'active'
  }
}

// --- 重置密码对话框（管理员输入新密码，design D2 契约） ---
const pwdDialogVisible = ref(false)
const pwdUser = ref<User | null>(null)
const pwdFormRef = ref<FormInstance>()
const pwdSaving = ref(false)
const pwdForm = reactive({ password: '' })
const pwdRules: FormRules = {
  password: [{ required: true, message: '请输入新密码', trigger: 'blur' }],
}

function onResetPwd(row: User) {
  pwdUser.value = row
  pwdForm.password = ''
  pwdDialogVisible.value = true
}

async function onPwdSubmit() {
  if (!pwdUser.value) {
    ElMessage.warning('未选择用户')
    return
  }
  if (!pwdFormRef.value) return
  await pwdFormRef.value.validate(async (valid) => {
    if (!valid) return
    pwdSaving.value = true
    try {
      await systemApi.resetPassword(pwdUser.value!.id, pwdForm.password)
      ElMessage.success('密码已重置，原密码已失效')
      pwdDialogVisible.value = false
    } catch {
      // 失败展示后端错误：由 client 拦截器按 detail 提示
    } finally {
      pwdSaving.value = false
    }
  })
}

async function onDeleteUser(row: User) {
  if (isAdminUserRow(row)) {
    ElMessage.warning('admin 用户不可删除')
    return
  }
  try {
    await ElMessageBox.confirm(`确定删除用户「${row.username}」？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await systemApi.deleteUser(row.id)
    ElMessage.success('已删除')
    loadUsers()
  } catch {
    // 错误提示由 client 拦截器按后端 detail 展示
  }
}

// --- 角色操作 ---
const roleDialogVisible = ref(false)
const editingRole = ref<Role | null>(null)

function openRoleCreate() {
  editingRole.value = null
  roleDialogVisible.value = true
}
function openRoleEdit(row: Role) {
  editingRole.value = { ...row }
  roleDialogVisible.value = true
}

async function onDeleteRole(row: Role) {
  if (isAdminRole(row)) {
    ElMessage.warning('admin 角色不可删除')
    return
  }
  try {
    await ElMessageBox.confirm(`确定删除角色「${row.name}」？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await systemApi.deleteRole(row.id)
    ElMessage.success('已删除')
    loadRoles()
    loadUsers()
  } catch {
    // 错误提示由 client 拦截器按后端 detail 展示（仍有用户 409 等）
  }
}

// --- 角色-用户绑定抽屉（design D7：成员列表 + 待绑定用户多选 + 覆盖式绑定） ---
const roleDrawerVisible = ref(false)
const drawerRole = ref<Role | null>(null)
const roleMembers = ref<User[]>([])
const membersLoading = ref(false)
const bindCandidates = ref<User[]>([])
const bindUserIds = ref<number[]>([])
const bindSaving = ref(false)

async function openRoleUsers(row: Role) {
  drawerRole.value = row
  bindUserIds.value = []
  roleDrawerVisible.value = true
  loadRoleMembers()
  // 待绑定候选 = 当前不属于该角色的用户（全量用户，不带查询条件）
  try {
    const all = await systemApi.getUsers()
    bindCandidates.value = all.filter((u) => u.role !== row.code)
  } catch {
    bindCandidates.value = []
  }
}

async function loadRoleMembers() {
  if (!drawerRole.value) return
  membersLoading.value = true
  try {
    roleMembers.value = await systemApi.getRoleUsers(drawerRole.value.id)
  } catch {
    // 错误提示由 client 拦截器按后端 detail 展示
  } finally {
    membersLoading.value = false
  }
}

async function onBindUsers() {
  if (!drawerRole.value || bindUserIds.value.length === 0) return
  bindSaving.value = true
  try {
    // 覆盖式提交：现有成员 + 新选用户（单角色语义下与「仅增量」等价，且兼容成员集合替换式后端）
    const desiredIds = [
      ...new Set([...roleMembers.value.map((u) => u.id), ...bindUserIds.value]),
    ]
    await systemApi.bindRoleUsers(drawerRole.value.id, desiredIds)
    ElMessage.success('绑定成功')
    bindUserIds.value = []
    // 成功后即时刷新成员列表、角色 user_count 与用户列表（被绑定用户出现在新角色下）
    await loadRoleMembers()
    await loadRoles()
    await loadUsers()
    // 刷新候选（被绑定用户移出候选）
    const all = await systemApi.getUsers()
    bindCandidates.value = all.filter((u) => u.role !== drawerRole.value!.code)
  } catch {
    // 错误提示由 client 拦截器按后端 detail 展示（admin 保护 403 等）
  } finally {
    bindSaving.value = false
  }
}

// --- 权限配置 ---
const permRoleCode = ref('')
const permDraft = ref<string[]>([])
const permSaving = ref(false)

const permRole = computed(() => roles.value.find((r) => r.code === permRoleCode.value) || null)
const menuPerms = computed(() => permissions.value.filter((p) => p.category === '菜单'))
const menuCodes = computed(() => menuPerms.value.map((p) => p.code))
const isAllMenu = computed(() =>
  menuCodes.value.length > 0 && menuCodes.value.every((c) => permDraft.value.includes(c)),
)
const isSomeMenu = computed(
  () => !isAllMenu.value && menuCodes.value.some((c) => permDraft.value.includes(c)),
)

function onPermRoleChange(code: string) {
  const r = roles.value.find((x) => x.code === code)
  permDraft.value = r ? [...r.perms] : []
}

function toggleAllMenu(v: boolean | string | number) {
  if (permRole.value && isAdminRole(permRole.value)) return
  const checked = Boolean(v)
  const set = new Set(permDraft.value)
  if (checked) menuCodes.value.forEach((c) => set.add(c))
  else menuCodes.value.forEach((c) => set.delete(c))
  permDraft.value = [...set]
}

function togglePerm(code: string, v: boolean | string | number) {
  if (permRole.value && isAdminRole(permRole.value)) return
  const checked = Boolean(v)
  const set = new Set(permDraft.value)
  if (checked) set.add(code)
  else set.delete(code)
  permDraft.value = [...set]
}

async function onSavePerms() {
  if (!permRole.value) return
  permSaving.value = true
  try {
    await systemApi.updateRole(permRole.value.id, { perms: permDraft.value })
    ElMessage.success('权限已保存')
    loadRoles()
  } catch {
    // 错误提示由 client 拦截器按后端 detail 展示（admin 角色保护 403 等）
  } finally {
    permSaving.value = false
  }
}

// --- LLM 供应商（design D8.1 / 6.5） ---
const llmProviders = ref<LlmProvider[]>([])
const llmLoading = ref(false)
const llmDialogVisible = ref(false)
const llmTestResult = ref<LlmTestResult | null>(null)

async function loadLlm() {
  llmLoading.value = true
  try {
    llmProviders.value = await systemApi.getLlmProviders()
  } catch {
    // handled
  } finally {
    llmLoading.value = false
  }
}

function openLlmCreate() {
  llmDialogVisible.value = true
}

async function onActivateLlm(row: LlmProvider) {
  try {
    await systemApi.activateLlmProvider(row.id)
    ElMessage.success(`已激活「${row.name}」，后续提问即时生效`)
    loadLlm()
  } catch {
    // handled
  }
}

async function onTestLlm(row: LlmProvider) {
  try {
    llmTestResult.value = await systemApi.testLlmProvider({ id: row.id })
  } catch (e) {
    llmTestResult.value = { ok: false, detail: e instanceof Error ? e.message : '测试请求失败' }
  }
}

async function onDeleteLlm(row: LlmProvider) {
  try {
    await ElMessageBox.confirm(`确定删除供应商预设「${row.name}」？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await systemApi.deleteLlmProvider(row.id)
    ElMessage.success('已删除')
    loadLlm()
  } catch {
    // handled
  }
}

// --- 辅助 ---
function fmtDate(ts: number) {
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
</script>

<style scoped>
.system-page {
  display: flex;
  flex-direction: column;
  gap: var(--sp-lg);
  flex: 1;
}

.system-tabs :deep(.el-tabs__header) {
  margin: 0;
  padding: 0 var(--sp-lg);
  border-bottom: 1px solid var(--border-base);
}
.system-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}
.system-tabs :deep(.el-tab-pane) {
  padding: 0 var(--sp-lg) var(--sp-lg);
}

.toolbar {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  padding: var(--sp-md) 0;
}
.toolbar .spacer {
  flex: 1;
}

/* 查询条（用户四条件 / 角色名） */
.filter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sp-sm);
  padding: var(--sp-md) 0;
}
.filter-bar .spacer {
  flex: 1;
}
.filter-item--name {
  width: 180px;
}
.filter-item--role {
  width: 140px;
}
.filter-item--status {
  width: 120px;
}
.filter-item--range {
  max-width: 280px;
}

/* 角色-用户绑定抽屉 */
.role-drawer {
  display: flex;
  flex-direction: column;
  gap: var(--sp-xl);
}
.drawer-section {
  display: flex;
  flex-direction: column;
  gap: var(--sp-sm);
}
.drawer-section__title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.drawer-hint {
  font-size: 12px;
}
.drawer-actions {
  display: flex;
  gap: var(--sp-sm);
  margin-top: var(--sp-sm);
}

.mono-col {
  font-family: var(--font-mono);
}

.text-disabled {
  color: var(--text-disabled);
}

/* 权限配置 */
.perm-config {
  padding: var(--sp-sm) 0;
}
.form-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: var(--sp-md);
}
.form-row label {
  font-size: 13px;
  color: var(--text-secondary);
}

.perm-tree {
  display: flex;
  flex-direction: column;
  gap: var(--sp-md);
  max-width: 560px;
}
.perm-group {
  display: flex;
  flex-direction: column;
}
.perm-node {
  height: 36px;
  display: flex;
  align-items: center;
  padding: 0 10px;
  border-radius: var(--r-sm);
  font-size: 13px;
}
.perm-node:hover {
  background: var(--bg-surface-hover);
}
.perm-node--parent {
  font-weight: 600;
}
.perm-children {
  margin-left: 26px;
  padding-left: 8px;
  border-left: 1px solid var(--border-base);
  display: flex;
  flex-direction: column;
}
.perm-code {
  font-size: 11px;
  color: var(--text-disabled);
  margin-left: 2px;
}
.admin-hint {
  font-size: 12px;
  margin-left: var(--sp-sm);
}

/* LLM 供应商 */
.llm-hint {
  font-size: 12px;
}
.llm-key {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-secondary);
  letter-spacing: 0.04em;
}
.llm-test-result {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  border-radius: var(--r-md);
  padding: var(--sp-sm) var(--sp-md);
  margin-bottom: var(--sp-md);
  line-height: 1.5;
}
.llm-test-result.is-ok {
  color: var(--fall);
  background: var(--fall-dim);
  border: 1px solid var(--fall);
}
.llm-test-result.is-fail {
  color: var(--rise);
  background: var(--rise-dim);
  border: 1px solid var(--rise);
}
.llm-test-result__close {
  width: 14px;
  height: 14px;
  cursor: pointer;
  opacity: 0.7;
}
.llm-test-result__close:hover {
  opacity: 1;
}
</style>
