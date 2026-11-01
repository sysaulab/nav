import { Link } from 'react-router-dom'

type CardProps = {
  to: string
  title: string
  description: string
  badge?: string
  disabled?: boolean
}

export default function Card({ to, title, description, badge, disabled }: CardProps) {
  const base =
    'block rounded-2xl border bg-white p-8 shadow-sm transition focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400'
  const enabled = 'border-slate-200 hover:border-slate-300 hover:shadow-md group'
  const off = 'border-slate-200 opacity-60 cursor-not-allowed'

  if (disabled) {
    return (
      <div className={`${base} ${off}`} aria-disabled="true">
        <CardBody title={title} description={description} badge={badge} />
      </div>
    )
  }

  return (
    <Link to={to} className={`${base} ${enabled}`}>
      <CardBody title={title} description={description} badge={badge} />
    </Link>
  )
}

function CardBody({
  title,
  description,
  badge,
}: Pick<CardProps, 'title' | 'description' | 'badge'>) {
  return (
    <>
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-medium text-slate-900">{title}</h2>
        {badge && (
          <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">
            {badge}
          </span>
        )}
      </div>
      <p className="mt-3 text-slate-600">{description}</p>
      <span className="mt-6 inline-block text-sm font-medium text-slate-900 group-hover:underline">
        Open →
      </span>
    </>
  )
}