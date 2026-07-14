// Run this only in the browser console at https://spotifyreleaselist.netlify.app
// It exports artist names/IDs only. Spotify access and refresh tokens never enter the file.
(async () => {
  const stored = localStorage.getItem('authData')
  if (!stored) throw new Error('Spotify Release List is not signed in. Refresh releases first.')

  const { token } = JSON.parse(stored)
  if (!token) throw new Error('No Spotify access token found. Refresh releases, then try again.')

  const artists = []
  let next = 'https://api.spotify.com/v1/me/following?type=artist&limit=50'

  while (next) {
    const response = await fetch(next, { headers: { Authorization: `Bearer ${token}` } })
    if (!response.ok) {
      throw new Error(`Spotify returned ${response.status}. Refresh releases and try again.`)
    }
    const page = (await response.json()).artists
    artists.push(...page.items.map(({ name, id }) => ({ name, id })))
    next = page.next
  }

  const escapeCsv = (value) => `"${String(value).replaceAll('"', '""')}"`
  const csv = [
    ['Artists', 'Artist IDs'],
    ...artists.sort((a, b) => a.name.localeCompare(b.name)).map(({ name, id }) => [name, id]),
  ].map((row) => row.map(escapeCsv).join(',')).join('\r\n')

  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const link = Object.assign(document.createElement('a'), {
    href: url,
    download: 'spotify-followed-artists.csv',
  })
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  console.log(`Exported ${artists.length} followed artists to spotify-followed-artists.csv`)
})().catch((error) => console.error('Followed-artist export failed:', error))

