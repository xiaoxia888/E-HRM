import { lazy, Suspense } from 'react'
import { Flex, Spin } from 'antd'
import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './layout/AppLayout'

const DashboardPage = lazy(() =>
  import('./pages/DashboardPage').then((module) => ({ default: module.DashboardPage })),
)
const ApplicationsPage = lazy(() =>
  import('./pages/ApplicationsPage').then((module) => ({ default: module.ApplicationsPage })),
)
const RightsPage = lazy(() =>
  import('./pages/RightsPage').then((module) => ({ default: module.RightsPage })),
)
const SocialSecurityPage = lazy(() =>
  import('./pages/SocialSecurityPage').then((module) => ({ default: module.SocialSecurityPage })),
)
const TaskCenterPage = lazy(() =>
  import('./pages/TaskCenterPage').then((module) => ({ default: module.TaskCenterPage })),
)
const SettingsPage = lazy(() =>
  import('./pages/SettingsPage').then((module) => ({ default: module.SettingsPage })),
)

export default function App() {
  return (
    <Suspense fallback={<Flex className="route-loading" align="center" justify="center"><Spin size="large" /></Flex>}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/applications" element={<ApplicationsPage />} />
          <Route path="/rights" element={<RightsPage />} />
          <Route path="/social-security" element={<SocialSecurityPage />} />
          <Route path="/tasks" element={<TaskCenterPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  )
}
