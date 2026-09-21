import { authHandlers } from './auth'
import { klineHandlers } from './kline'
import { watchlistHandlers } from './watchlist'
import { stockHandlers } from './stock'
import { qaHandlers } from './qa'
import { bspHandlers } from './bsp'
import { monitorHandlers } from './monitor'
import { performanceHandlers } from './performance'
import { screenerHandlers } from './screener'
import { alertsHandlers } from './alerts'
import { systemHandlers } from './system'

export const handlers = [
  ...authHandlers,
  ...klineHandlers,
  ...watchlistHandlers,
  ...stockHandlers,
  ...qaHandlers,
  ...bspHandlers,
  ...monitorHandlers,
  ...performanceHandlers,
  ...screenerHandlers,
  ...alertsHandlers,
  ...systemHandlers,
]
