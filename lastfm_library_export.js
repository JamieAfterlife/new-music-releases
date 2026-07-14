// Run this only in the browser console on your Last.fm library/artists page.
// It exports public artist names, scrobble counts, and Last.fm URLs only.
(async () => {
  const match = location.pathname.match(/^\/user\/([^/]+)\/library\/artists/i)
  if (!match) throw new Error('Open your Last.fm Library > Artists page before running this.')

  const user = match[1]
  const artists = new Map()
  let page = 1

  while (true) {
    const response = await fetch(`/user/${user}/library/artists?page=${page}`)
    if (!response.ok) throw new Error(`Last.fm returned ${response.status} on page ${page}.`)
    const documentCopy = new DOMParser().parseFromString(await response.text(), 'text/html')
    const rows = [...documentCopy.querySelectorAll('.chartlist-row')]
    if (!rows.length) break

    for (const row of rows) {
      const artistLink = row.querySelector('.chartlist-artist a, .chartlist-name a')
      const countNode = row.querySelector(
        '.chartlist-count-bar-value, .chartlist-count-bar-link, .chartlist-count-bar'
      )
      const name = artistLink?.textContent.trim()
      const count = Number((countNode?.textContent || '').replace(/\D/g, ''))
      if (name) artists.set(name, { name, count, url: artistLink.href })
    }

    const next = documentCopy.querySelector('.pagination-next:not(.pagination-next--disabled) a, a.pagination-next')
    console.log(`Read Last.fm page ${page}; ${artists.size} artists so far`)
    if (!next || rows.length === 0) break
    page += 1
  }

  const escapeCsv = (value) => `"${String(value).replaceAll('"', '""')}"`
  const csv = [
    ['Artists', 'Scrobbles', 'Last.fm URL'],
    ...[...artists.values()]
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
      .map(({ name, count, url }) => [name, count, url]),
  ].map((row) => row.map(escapeCsv).join(',')).join('\r\n')

  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const link = Object.assign(document.createElement('a'), {
    href: url,
    download: `lastfm-${user}-artists.csv`,
  })
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  console.log(`Exported ${artists.size} artists to lastfm-${user}-artists.csv`)
})().catch((error) => console.error('Last.fm artist export failed:', error))

