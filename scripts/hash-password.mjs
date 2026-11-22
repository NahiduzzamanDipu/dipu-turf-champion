import { pbkdf2Sync, randomBytes } from 'node:crypto'
import { stdin, stdout } from 'node:process'

if (!stdin.isTTY || typeof stdin.setRawMode !== 'function') throw new Error('Run this script in an interactive terminal.')
stdin.setRawMode(true)
stdin.resume()
stdout.write('Choose an owner password (minimum 12 characters): ')
const password = await new Promise((resolve, reject) => {
  let value = ''
  stdin.on('data', chunk => {
    const text = chunk.toString('utf8')
    if (text === '\u0003') { stdin.setRawMode(false); reject(new Error('Cancelled')); return }
    if (text === '\r' || text === '\n') {
      stdin.setRawMode(false)
      stdout.write('\n')
      resolve(value)
      return
    }
    if (text === '\u007f' || text === '\b') {
      value = value.slice(0, -1)
      stdout.write('\b \b')
      return
    }
    if (text >= ' ' && text.length) { value += text; stdout.write('*'.repeat(text.length)) }
  })
})
if (password.length < 12) throw new Error('Password must be at least 12 characters.')
const salt = randomBytes(16)
const hash = pbkdf2Sync(password, salt, 600000, 32, 'sha256')
console.log(`pbkdf2-sha256$600000$${salt.toString('base64')}$${hash.toString('base64')}`)
