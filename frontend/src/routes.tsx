// HashRouter：后端只需 StaticFiles(html=True)，不需要 SPA fallback（plan §4.6）
// 课程 id 放路径：#/courses/:id/materials（plan §4.6）
import { useQuery } from '@tanstack/react-query'
import { HashRouter, Navigate, Outlet, Route, Routes, useLocation, useParams } from 'react-router'
import { AppShell, type TabKey } from './components/AppShell'
import { getCourse } from './api/endpoints'
import { CoursesPage } from './pages/Courses'
import { DashboardPage } from './pages/Dashboard'
import { MaterialsPage } from './pages/Materials'
import { MaterialDetailPage } from './pages/MaterialDetail'
import { KnowledgePage } from './pages/Knowledge'
import { QuizPage } from './pages/Quiz'
import { ReviewPage } from './pages/Review'
import { PlanPage } from './pages/Plan'
import { SettingsPage } from './pages/Settings'

function tabFromPath(pathname: string): TabKey {
  if (pathname.includes('/knowledge')) return 'knowledge'
  if (pathname.includes('/quiz')) return 'quiz'
  if (pathname.includes('/review')) return 'review'
  if (pathname.includes('/plan')) return 'plan'
  if (pathname.includes('/materials')) return 'materials'
  return 'overview'
}

/** 课程页公共骨架：加载课程 → crumb + tab */
function CourseLayout() {
  const { courseId } = useParams()
  const location = useLocation()
  const course = useQuery({
    queryKey: ['course', courseId],
    queryFn: () => getCourse(courseId!),
    enabled: courseId !== undefined,
    retry: false,
  })

  if (course.isError) {
    return (
      <AppShell>
        <p className="rounded-md border border-error/40 bg-error-bg px-4 py-3 text-[14px] text-ink">
          课程不存在或已删除。<a href="#/" className="text-accent">返回我的课程</a>
        </p>
      </AppShell>
    )
  }

  return (
    <AppShell course={course.data ?? null} active={tabFromPath(location.pathname)}>
      <Outlet />
    </AppShell>
  )
}

export function AppRoutes() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<CoursesPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/courses/:courseId" element={<CourseLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="materials" element={<MaterialsPage />} />
          <Route path="materials/:materialId" element={<MaterialDetailPage />} />
          <Route path="knowledge" element={<KnowledgePage />} />
          <Route path="quiz" element={<QuizPage />} />
          <Route path="review" element={<ReviewPage />} />
          <Route path="plan" element={<PlanPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </HashRouter>
  )
}
