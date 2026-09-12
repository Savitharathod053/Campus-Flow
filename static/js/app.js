// Campus Flow — Interactive Modern Platform JavaScript

document.addEventListener('DOMContentLoaded', () => {
    // ---------------------------------------------------------
    // 1. Alert Auto-Dismissal & Form Toggles
    // ---------------------------------------------------------
    const alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(alert => {
        setTimeout(() => {
            try {
                const bsAlert = new bootstrap.Alert(alert);
                bsAlert.close();
            } catch (e) {}
        }, 6000);
    });

    // Toggle free event pricing input in event creation
    const isFreeCheckbox = document.getElementById('is_free');
    const feeInputGroup = document.getElementById('fee_input_group');
    const feeInput = document.getElementById('registration_fee');

    if (isFreeCheckbox && feeInputGroup) {
        const toggleFee = () => {
            if (isFreeCheckbox.checked) {
                feeInputGroup.style.display = 'none';
                if (feeInput) feeInput.value = '0.0';
            } else {
                feeInputGroup.style.display = 'block';
            }
        };
        isFreeCheckbox.addEventListener('change', toggleFee);
        toggleFee();
    }

    // ---------------------------------------------------------
    // 2. Dynamic Time-Based Greeting
    // ---------------------------------------------------------
    initDynamicGreetings();

    // ---------------------------------------------------------
    // 3. Glassmorphic Frosted Navbar on Scroll
    // ---------------------------------------------------------
    initGlassNavbar();

    // ---------------------------------------------------------
    // 4. Card Depth & 3D Tilt Interaction
    // ---------------------------------------------------------
    initCardTilt();

    // ---------------------------------------------------------
    // 5. Animated Numeric Stat Counters
    // ---------------------------------------------------------
    initStatCounters();

    // ---------------------------------------------------------
    // 6. Scroll-Reveal Animation System
    // ---------------------------------------------------------
    initScrollReveal();

    // ---------------------------------------------------------
    // 7. Click-to-Copy for Passes and Certificates
    // ---------------------------------------------------------
    initCopyButtons();
});


/* ==========================================================================
   Interactive UI Feature Functions
   ========================================================================== */

/**
 * Updates greeting elements with local time-aware greetings:
 * "Good Morning", "Good Afternoon", or "Good Evening".
 */
function initDynamicGreetings() {
    const greetingElements = document.querySelectorAll('.dynamic-greeting, [data-greeting]');
    if (!greetingElements.length) return;

    const hour = new Date().getHours();
    let greetingText = 'Good Morning';
    let greetingIcon = 'bi-brightness-high';

    if (hour >= 12 && hour < 17) {
        greetingText = 'Good Afternoon';
        greetingIcon = 'bi-sun';
    } else if (hour >= 17 || hour < 5) {
        greetingText = 'Good Evening';
        greetingIcon = 'bi-moon-stars';
    }

    greetingElements.forEach(el => {
        const name = el.dataset.userName || '';
        el.innerHTML = `${greetingText}${name ? ', ' + name : ''} 👋`;
    });
}


/**
 * Toggles a frosted glassmorphic state on .ff-navbar when scrolled down.
 */
function initGlassNavbar() {
    const navbar = document.querySelector('.ff-navbar');
    if (!navbar) return;

    const handleScroll = () => {
        if (window.scrollY > 15) {
            navbar.classList.add('navbar-scrolled');
        } else {
            navbar.classList.remove('navbar-scrolled');
        }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    handleScroll();
}


/**
 * Adds subtle 3D tilt-on-hover effect to interactive cards and dashboard stat cards,
 * tracking mouse position across the card surface.
 * Respects prefers-reduced-motion and disables on touch devices.
 */
function initCardTilt() {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const isFinePointer = window.matchMedia('(pointer: fine)').matches;
    if (prefersReducedMotion || !isFinePointer) return;

    // Only apply subtle tilt to cards that explicitly request it
    const candidateCards = document.querySelectorAll('.tilt-card');

    candidateCards.forEach(card => {
        // Exclude cards that contain whole data tables or interactive forms
        if (card.querySelector('table') || card.querySelector('form')) return;

        let isHovered = false;

        card.addEventListener('mouseenter', () => {
            isHovered = true;
            card.style.transition = 'transform 0.12s ease-out, box-shadow 0.2s ease, border-color 0.2s ease';
        });

        card.addEventListener('mousemove', (e) => {
            if (!isHovered) return;
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            const centerX = rect.width / 2;
            const centerY = rect.height / 2;

            // Gentle, contained rotation limits (max 2.5 degrees, no translateZ)
            const maxTilt = 2.5;
            const tiltX = -((y - centerY) / centerY) * maxTilt;
            const tiltY = ((x - centerX) / centerX) * maxTilt;

            card.style.transform = `rotateX(${tiltX.toFixed(2)}deg) rotateY(${tiltY.toFixed(2)}deg) translateY(-3px)`;
        });

        card.addEventListener('mouseleave', () => {
            isHovered = false;
            card.style.transition = 'transform 0.28s ease, box-shadow 0.25s ease, border-color 0.2s ease';
            card.style.transform = '';
        });
    });
}


/**
 * Animates numeric stat counters from 0 to their target value
 * when they enter the viewport using IntersectionObserver.
 */
function initStatCounters() {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const elements = document.querySelectorAll(
        '.count-up, [data-counter], .metric-number, .card.border-start h3, .row.g-3 > [class*="col-"] > .card h3'
    );
    if (!elements.length) return;

    const counterElements = [];
    elements.forEach(el => {
        const text = el.textContent.trim();
        if (/^\d+\+?$/.test(text)) {
            if (!el.dataset.target) {
                el.dataset.target = text.replace(/[^\d]/g, '');
                if (text.includes('+')) el.dataset.plus = 'true';
            }
            counterElements.push(el);
        } else if (el.dataset.target) {
            counterElements.push(el);
        }
    });

    if (!counterElements.length) return;

    if (!('IntersectionObserver' in window) || prefersReducedMotion) {
        counterElements.forEach(el => {
            if (el.dataset.target) {
                const hasPlus = el.dataset.plus === 'true' || el.textContent.includes('+');
                el.textContent = el.dataset.target + (hasPlus ? '+' : '');
            }
        });
        return;
    }

    const counterObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            const el = entry.target;
            observer.unobserve(el);

            const rawTarget = el.dataset.target || el.textContent.replace(/[^\d]/g, '');
            const targetVal = parseInt(rawTarget, 10);
            if (isNaN(targetVal) || targetVal === 0) return;

            const hasPlus = el.dataset.plus === 'true' || el.textContent.includes('+');
            const duration = 1200; // ms
            const startTime = performance.now();

            const updateCount = (currentTime) => {
                const elapsed = currentTime - startTime;
                const progress = Math.min(elapsed / duration, 1);
                const easeOut = 1 - Math.pow(1 - progress, 3);
                const currentVal = Math.floor(easeOut * targetVal);

                el.textContent = currentVal.toLocaleString() + (hasPlus ? '+' : '');

                if (progress < 1) {
                    requestAnimationFrame(updateCount);
                } else {
                    el.textContent = targetVal.toLocaleString() + (hasPlus ? '+' : '');
                }
            };

            requestAnimationFrame(updateCount);
        });
    }, { threshold: 0.15 });

    counterElements.forEach(el => counterObserver.observe(el));
}


/**
 * Animates elements smoothly into view as user scrolls down the page.
 */
function initScrollReveal() {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion || !('IntersectionObserver' in window)) {
        document.querySelectorAll('.reveal-on-scroll').forEach(el => {
            el.classList.add('is-revealed');
        });
        return;
    }

    document.querySelectorAll(
        '.event-card, .certificate-vault-card'
    ).forEach((card, idx) => {
        if (!card.classList.contains('reveal-on-scroll')) {
            card.classList.add('reveal-on-scroll');
            const delayClass = `reveal-delay-${(idx % 4) + 1}`;
            card.classList.add(delayClass);
        }
    });

    const revealElements = document.querySelectorAll('.reveal-on-scroll');
    if (!revealElements.length) return;

    const revealObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('is-revealed');
                observer.unobserve(entry.target);
            }
        });
    }, {
        threshold: 0.08,
        rootMargin: '0px 0px -40px 0px'
    });

    revealElements.forEach(el => revealObserver.observe(el));
}


/**
 * Provides 1-click clipboard copying for ticket pass codes and certificate credentials.
 */
function initCopyButtons() {
    const copyBtns = document.querySelectorAll('[data-copy-target]');
    copyBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const textToCopy = btn.dataset.copyTarget;
            if (!textToCopy) return;

            navigator.clipboard.writeText(textToCopy).then(() => {
                const originalHtml = btn.innerHTML;
                btn.innerHTML = '<i class="bi bi-check2 text-success me-1"></i> Copied!';
                btn.classList.add('border-success');
                setTimeout(() => {
                    btn.innerHTML = originalHtml;
                    btn.classList.remove('border-success');
                }, 2200);
            }).catch(() => {});
        });
    });
}
