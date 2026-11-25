import { defineStore } from 'pinia'
import { ref } from 'vue'
import Cookies from 'js-cookie'

export const useUserStore = defineStore('user', () => {
  const token = ref(Cookies.get('token') || '')
  const user = ref(JSON.parse(Cookies.get('user') || '{}'))
  const scenario = ref(Cookies.get('scenario') || 'ecommerce')
  const scenarios = ref([])

  function setSession(newToken, newUser) {
    token.value = newToken
    user.value = newUser
    Cookies.set('token', newToken, { expires: 7 })
    Cookies.set('user', JSON.stringify(newUser), { expires: 7 })
  }
  function setScenario(code) {
    const next = code || 'ecommerce'
    scenario.value = next
    Cookies.set('scenario', next, { expires: 30 })
  }
  function setScenarios(list) {
    scenarios.value = Array.isArray(list) ? list : []
  }
  function logout() {
    token.value = ''
    user.value = {}
    Cookies.remove('token')
    Cookies.remove('user')
  }
  return { token, user, scenario, scenarios, setSession, setScenario, setScenarios, logout }
})
