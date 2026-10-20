// 我的课程：行式列表（F-2）+ 新建/编辑 + 删除二次确认（204 无体）
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { useState, type FormEvent } from 'react'
import {
  createCourse,
  deleteCourse,
  listCourses,
  updateCourse,
  type Course,
} from '../api/endpoints'
import { ApiError } from '../api/client'
import { AppShell } from '../components/AppShell'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import { ErrorNotice } from '../components/ErrorNotice'

function formatDate(iso: string): string {
  return iso.slice(0, 10)
}

/** 新建 / 编辑共用表单卡（编辑时传入初始值） */
function CourseForm({
  initial,
  onDone,
  onCancel,
}: {
  initial?: Course
  onDone: () => void
  onCancel: () => void
}) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [fieldError, setFieldError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: () =>
      initial
        ? updateCourse(initial.id, { name: name.trim(), description: description.trim() })
        : createCourse({ name: name.trim(), description: description.trim() }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['courses'] })
      onDone()
    },
    onError: (err) => {
      if (err instanceof ApiError && err.code === 'VALIDATION_ERROR') {
        setFieldError('课程名不能为空（≤100 字）')
      } else {
        setFieldError(err instanceof ApiError ? err.displayMessage : String(err))
      }
    },
  })

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (name.trim() === '') {
      setFieldError('请填写课程名')
      return
    }
    setFieldError(null)
    save.mutate()
  }

  return (
    <form
      onSubmit={onSubmit}
      className="mb-4 rounded-lg border border-border bg-surface px-5 py-4"
      aria-label={initial ? '编辑课程' : '新建课程'}
    >
      <h2 className="text-[15px] font-semibold">{initial ? '编辑课程' : '新建课程'}</h2>
      <div className="mt-3 grid max-w-xl gap-3">
        <label className="grid gap-1 text-[13px] text-ink2">
          课程名 *
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={100}
            placeholder="如：计算机网络·运输层"
            className="h-9 rounded-md border border-border2 bg-bg px-3 text-sm text-ink outline-none focus:border-accent"
          />
        </label>
        <label className="grid gap-1 text-[13px] text-ink2">
          描述
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            maxLength={500}
            placeholder="考试时间、教材、备注（可选）"
            className="rounded-md border border-border2 bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent"
          />
        </label>
        {fieldError && <p className="text-[13px] text-error">{fieldError}</p>}
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={save.isPending}
            className="rounded-md bg-accent px-3.5 py-1.5 text-[13px] font-medium text-white disabled:opacity-50"
          >
            {save.isPending ? '保存中…' : '保存'}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-border2 px-3.5 py-1.5 text-[13px] text-ink2 hover:text-ink"
          >
            取消
          </button>
        </div>
      </div>
    </form>
  )
}

export function CoursesPage() {
  const courses = useQuery({ queryKey: ['courses'], queryFn: listCourses })
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<Course | null>(null)
  const [deleting, setDeleting] = useState<Course | null>(null)
  const [deleteError, setDeleteError] = useState<unknown>(null)

  const remove = useMutation({
    mutationFn: (id: string) => deleteCourse(id),
    onSuccess: () => {
      setDeleting(null)
      setDeleteError(null)
      queryClient.invalidateQueries({ queryKey: ['courses'] })
    },
    onError: (err) => setDeleteError(err),
  })

  const list = courses.data ?? []

  return (
    <AppShell>
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-[22px] font-bold">我的课程</h1>
        {!creating && !editing && (
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="rounded-md bg-accent px-3.5 py-1.5 text-[13px] font-medium text-white"
          >
            + 新建课程
          </button>
        )}
      </div>

      {deleteError != null && (
        <div className="mb-3">
          <ErrorNotice error={deleteError} />
        </div>
      )}

      {courses.isError && <ErrorNotice error={courses.error} />}

      {creating && (
        <CourseForm onDone={() => setCreating(false)} onCancel={() => setCreating(false)} />
      )}
      {editing && (
        <CourseForm initial={editing} onDone={() => setEditing(null)} onCancel={() => setEditing(null)} />
      )}

      {courses.isLoading && <p className="text-[13px] text-ink3">加载中…</p>}

      {!courses.isLoading && list.length === 0 && (
        <EmptyState
          title="还没有课程"
          action={
            <button
              type="button"
              onClick={() => setCreating(true)}
              className="rounded-md bg-accent px-3.5 py-1.5 text-[13px] font-medium text-white"
            >
              创建第一门课
            </button>
          }
        >
          建一门课程（如「计算机网络·运输层」），上传课件后即可生成知识框架与测验。
        </EmptyState>
      )}

      {list.length > 0 && (
        <section className="overflow-hidden rounded-lg border border-border bg-surface">
          {list.map((course) => (
            <div
              key={course.id}
              className="group flex items-center gap-4 border-t border-border px-5 py-3 first:border-t-0 hover:bg-bg focus-within:bg-bg"
            >
              <div className="min-w-0 flex-1">
                <Link
                  to={`/courses/${course.id}`}
                  className="text-[14.5px] font-semibold text-ink no-underline hover:text-accent"
                >
                  {course.name}
                </Link>
                <div className="mt-0.5 truncate text-[12.5px] text-ink3">
                  {course.description || '无描述'}
                </div>
              </div>
              <span className="flex-none text-xs text-ink3">更新 {formatDate(course.updated_at)}</span>
              <span className="flex flex-none gap-3 text-xs text-ink3 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                <button type="button" className="text-accent" onClick={() => setEditing(course)}>
                  编辑
                </button>
                <button type="button" className="text-error" onClick={() => setDeleting(course)}>
                  删除
                </button>
              </span>
            </div>
          ))}
        </section>
      )}

      <ConfirmDialog
        open={deleting !== null}
        title={`删除课程「${deleting?.name ?? ''}」？`}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
        onCancel={() => {
          setDeleting(null)
          setDeleteError(null)
        }}
      >
        课程下的资料、知识框架与测验记录都会一并删除，此操作不可撤销。
      </ConfirmDialog>
    </AppShell>
  )
}
