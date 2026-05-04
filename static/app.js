(() => {
    const api = {
        async json(url, options = {}) {
            const response = await fetch(url, options);
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.message || 'Request failed');
            }
            return data;
        },
    };

    async function fetchCities(query) {
        const data = await api.json(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(query)}&count=5&language=ru&format=json`);
        return data.results || [];
    }

    function renderCities(input, suggestions, results, onPick) {
        suggestions.innerHTML = '';
        if (!results.length) {
            suggestions.innerHTML = '<div class="suggestion-item text-muted">Ничего не нашла</div>';
            suggestions.classList.remove('d-none');
            return;
        }
        results.forEach((city) => {
            const item = document.createElement('div');
            item.className = 'suggestion-item';
            item.textContent = `${city.name}${city.admin1 ? ', ' + city.admin1 : ''}${city.country ? ', ' + city.country : ''}`;
            item.addEventListener('click', () => onPick(`${city.name}${city.country ? ', ' + city.country : ''}`));
            suggestions.appendChild(item);
        });
        suggestions.classList.remove('d-none');
    }

    function initHome() {
        const input = document.getElementById('location-input');
        const title = document.getElementById('location-title');
        const uv = document.getElementById('uv-value');
        const temp = document.getElementById('temp-value');
        const suggestions = document.getElementById('suggestions');
        if (!input || !title || !uv || !temp || !suggestions) {
            return;
        }

        let timer = null;

        function hideSuggestions() {
            suggestions.innerHTML = '';
            suggestions.classList.add('d-none');
        }

        function setEmpty() {
            title.textContent = 'Выбери локацию';
            uv.textContent = '—';
            temp.textContent = '—';
        }

        async function loadWeather(query) {
            if (query.length < 3) {
                setEmpty();
                hideSuggestions();
                return;
            }
            try {
                const data = await api.json(`/api/current-weather?location=${encodeURIComponent(query)}`);
                if (input.value.trim() !== query) return;
                const weather = data.weather || {};
                title.textContent = weather.location || 'Локация';
                uv.textContent = weather.uv ?? '—';
                temp.textContent = weather.temp == null || weather.temp === '' ? '—' : `${Math.round(weather.temp)}°`;
            } catch {
                if (input.value.trim() === query) hideSuggestions();
            }
        }

        input.addEventListener('input', () => {
            const query = input.value.trim();
            setEmpty();
            clearTimeout(timer);
            timer = setTimeout(async () => {
                loadWeather(query);
                if (query.length < 3) {
                    hideSuggestions();
                    return;
                }
                try {
                    const results = await fetchCities(query);
                    if (input.value.trim() !== query) return;
                    renderCities(input, suggestions, results, (value) => {
                        input.value = value;
                        hideSuggestions();
                        loadWeather(value.trim());
                    });
                } catch {
                    if (input.value.trim() === query) hideSuggestions();
                }
            }, 250);
        });

        document.addEventListener('click', (event) => {
            if (!suggestions.contains(event.target) && event.target !== input) {
                hideSuggestions();
            }
        });
    }

    function initForm() {
        const input = document.getElementById('location-input');
        const suggestions = document.getElementById('suggestions');
        const status = document.getElementById('location-status');
        const dateInput = document.getElementById('date');
        const timeInput = document.getElementById('start_time');
        const uv = document.getElementById('uv_index');
        const temp = document.getElementById('temp_value');
        const submit = document.getElementById('submit-button');
        const hadTan = document.getElementById('had_tan');
        const wasOutside = document.getElementById('was_outside');
        const durationWrap = document.getElementById('duration-wrap');
        const durationInput = document.getElementById('duration-input');
        if (!input || !dateInput || !timeInput || !uv || !temp || !submit) {
            return;
        }

        let timer = null;
        let context = null;

        function hideSuggestions() {
            if (suggestions) {
                suggestions.innerHTML = '';
                suggestions.classList.add('d-none');
            }
        }

        function setStatus(kind, message) {
            if (!status) {
                return;
            }
            if (!message) {
                status.className = 'location-status d-none';
                status.textContent = '';
                return;
            }
            status.className = `location-status ${kind}`;
            status.textContent = message;
        }

        function clearWeather() {
            uv.value = '';
            temp.value = '';
        }

        function toggleDuration() {
            const show = hadTan && hadTan.value === 'yes' && wasOutside && wasOutside.value === 'yes';
            if (durationWrap) {
                durationWrap.classList.toggle('d-none', !show);
            }
            if (durationInput) {
                durationInput.required = show;
                if (!show) {
                    durationInput.value = '';
                }
            }
        }

        function currentStamp() {
            return context && context.local_now ? String(context.local_now).slice(0, 16) : '';
        }

        function validateTime() {
            const stamp = currentStamp();
            if (!stamp) {
                submit.disabled = false;
                return;
            }
            const chosen = dateInput.value && timeInput.value ? `${dateInput.value}T${timeInput.value}` : '';
            dateInput.max = stamp.slice(0, 10);
            timeInput.max = dateInput.value === stamp.slice(0, 10) ? stamp.slice(11, 16) : '';
            if (chosen && chosen > stamp) {
                setStatus('error', `Будущее время в ${context.location} выбрать нельзя. Сейчас там ${stamp.replace('T', ' ')}.`);
                submit.disabled = true;
                clearWeather();
                return;
            }
            submit.disabled = false;
            setStatus('info', `Сейчас в ${context.location}: ${stamp.replace('T', ' ')}.`);
        }

        async function loadContext(query) {
            if (query.length < 3) {
                context = null;
                setStatus('', '');
                clearWeather();
                submit.disabled = false;
                return;
            }
            try {
                const data = await api.json(`/api/location-context?location=${encodeURIComponent(query)}`);
                if (input.value.trim() !== query) {
                    return;
                }
                context = data;
                setStatus('info', `Сейчас в ${data.country ? `${data.location}, ${data.country}` : data.location}: ${String(data.local_now || '').replace('T', ' ')}.`);
                validateTime();
            } catch (error) {
                if (input.value.trim() === query) {
                    context = null;
                    setStatus('error', 'Не удалось определить локацию.');
                    clearWeather();
                    submit.disabled = true;
                }
            }
        }

        async function loadWeather(query) {
            if (query.length < 3 || !dateInput.value || !timeInput.value) {
                clearWeather();
                return;
            }
            const stamp = `${query}|${dateInput.value}|${timeInput.value}`;
            try {
                const data = await api.json(`/api/uv?location=${encodeURIComponent(query)}&date=${encodeURIComponent(dateInput.value)}&time=${encodeURIComponent(timeInput.value)}`);
                const currentStampValue = `${input.value.trim()}|${dateInput.value}|${timeInput.value}`;
                if (stamp !== currentStampValue) {
                    return;
                }
                uv.value = data.weather && data.weather.uv != null ? data.weather.uv : '';
                temp.value = data.weather && data.weather.temp != null ? `${Math.round(data.weather.temp)}°` : '';
            } catch (error) {
                const currentStampValue = `${input.value.trim()}|${dateInput.value}|${timeInput.value}`;
                if (stamp === currentStampValue) {
                    clearWeather();
                }
            }
        }

        input.addEventListener('input', () => {
            context = null;
            clearWeather();
            setStatus('', '');
            submit.disabled = false;
            hideSuggestions();
            clearTimeout(timer);
            const query = input.value.trim();
            timer = setTimeout(() => {
                loadContext(query);
                loadWeather(query);
            }, 250);
        });

        if (suggestions) {
            input.addEventListener('input', async () => {
                const query = input.value.trim();
                if (query.length < 3) {
                    hideSuggestions();
                    return;
                }
                try {
                    const results = await fetchCities(query);
                    if (input.value.trim() !== query) {
                        return;
                    }
                    renderCities(input, suggestions, results, (value) => {
                        input.value = value;
                        hideSuggestions();
                        loadContext(value);
                        loadWeather(value);
                    });
                } catch {
                    if (input.value.trim() === query) {
                        hideSuggestions();
                    }
                }
            });
        }

        [dateInput, timeInput].forEach((field) => {
            field.addEventListener('input', () => {
                validateTime();
                loadWeather(input.value.trim());
            });
            field.addEventListener('change', () => {
                validateTime();
                loadWeather(input.value.trim());
            });
        });

        [hadTan, wasOutside].forEach((field) => {
            if (field) {
                field.addEventListener('change', toggleDuration);
            }
        });

        document.addEventListener('click', (event) => {
            if (suggestions && !suggestions.contains(event.target) && event.target !== input) {
                hideSuggestions();
            }
        });

        toggleDuration();
        loadContext(input.value.trim());
        loadWeather(input.value.trim());
    }

    document.addEventListener('DOMContentLoaded', () => {
        if (document.getElementById('location-title')) {
            initHome();
        }
        if (document.getElementById('sessionForm')) {
            initForm();
        }
    });
})();
